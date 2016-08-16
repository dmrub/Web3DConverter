# Initialization
import hashlib
import mimetypes
import os
import shutil
import threading
import subprocess
import tempfile

import requests
from flask import Flask, render_template, jsonify, request, send_from_directory, abort, after_this_request
from flask.json import JSONEncoder
import six
from six.moves.urllib.parse import urlparse
from werkzeug.utils import secure_filename
from filedb import FileDB, FileEntry

mimetypes.init()

extensions = {
    '.cpp': 'cpp',
    '.hpp': 'cpp',
    '.h++': 'cpp',
    '.c++': 'cpp',
    '.cc': 'cpp',
    '.hh': 'cpp',
    '.h': 'c',
    '.c': 'c',
    '.java': 'java',
    '.py': 'python',
    '.sh': 'bash',
    '.css': 'css',
    '.cs': 'csharp',
    '.html': 'html',
    '.htm': 'html'
}


def run_command(command, env=None, cwd=None):
    """returns triple (returncode, stdout, stderr)"""
    myenv = {}
    if env is not None:
        for k, v in env.items():
            myenv[str(k)] = str(v)
    env = myenv
    if isinstance(command, list) or isinstance(command, tuple):
        p = subprocess.Popen(command,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             env=env,
                             cwd=cwd,
                             universal_newlines=False)
    else:
        p = subprocess.Popen(command,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             env=env,
                             cwd=cwd,
                             universal_newlines=False,
                             shell=True)
    out = p.stdout.read()
    p.stdout.close()
    err = p.stderr.read()
    p.stderr.close()
    status = p.wait()

    return status, out, err


class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        return JSONEncoder.default(self, obj)


# create application
app = Flask(__name__, instance_relative_config=True)
app.json_encoder = CustomJSONEncoder

logger = app.logger

# Load default config and override config from an environment variable
app.config.update(dict(
    SECRET_KEY=os.urandom(24),
    LOG_FILE=os.path.join(app.instance_path, 'ldrconverter.log'),
    FILE_FOLDER=os.path.join(app.instance_path, 'files'),
    LDRCONVERT='ldrconvert',
    ASSIMP='assimp',
    LDRAWDIR=os.getenv('LDRAWDIR', '/usr/share/ldraw'),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024  # Maximal 100 Mb for files
))
app.config.from_envvar('LDR_CONVERTER_SETTINGS', silent=True)

app.json_encoder = CustomJSONEncoder


class FileManager(object):
    def __init__(self, file_folder):
        self.fdb = FileDB(file_folder)
        self.tmp_folder = os.path.join(file_folder, 'tmp')
        shutil.rmtree(self.tmp_folder, ignore_errors=True, onerror=None)
        if not os.path.exists(self.tmp_folder):
            os.makedirs(self.tmp_folder)
        self.remove_files = []
        self.lock = threading.RLock()

    def remove_later(self, filename):
        with self.lock:
            logger.info('Remove later {}'.format(filename))
            self.remove_files.append(filename)

    def sync(self):
        with self.lock:
            for f in self.remove_files:
                remove = getattr(f, 'remove', None)
                logger.info("Removing file: {}".format(f))
                if callable(remove):
                    remove()
                else:
                    os.remove(f)
            del self.remove_files[:]
            self.fdb.sync()

    def __del__(self):
        self.sync()


def hash_file(filename):
    BLOCKSIZE = 65536
    hasher = hashlib.sha1()
    with open(filename, 'rb') as fd:
        buf = fd.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = fd.read(BLOCKSIZE)
    return hasher.hexdigest()


@app.before_first_request
def pre_first_request():
    pass


@app.before_request
def pre_request():
    global FM
    FM.sync()


def error_response(message, status_code=500):
    response = jsonify({'message': message})
    response.status_code = status_code
    return response


class FileFormat(object):
    def __init__(self, name, description, mimetype, ext):
        self.name = name
        self.description = description
        self.mimetype = mimetype
        self.ext = ext

    def __repr__(self):
        return "FileFormat(name={!r}, description={!r}, mimetype={!r}, ext={!r})".format(
            self.name, self.description, self.mimetype, self.ext)


FORMAT_INFO = {
    'ldr': FileFormat("LDR", "LDraw file format", "text/plain", ".ldr"),
    '3ds': FileFormat("3DS", "3D Studio", "application/octet-stream", ".3ds"),
    'mpd': FileFormat("MPD", "LDraw Multi-Part Documents", "text/plain", ".mpd"),
    'obj': FileFormat("OBJ", "Wavefront OBJ", "text/plain", ".obj"),
    'blend': FileFormat("BLEND", "Blender", "application/octet-stream", ".blend"),
    'bvh': FileFormat("BVH", "Biovision BVH", "text/plain", ".bvh"),
    'ply': FileFormat("PLY", "Stanford Polygon Library", "application/octet-stream", ".ply"),
    'smd': FileFormat("SMD", "Studiomdl Data file format", "text/plain", ".smd")
}


def derive_format(filename):
    global FORMAT_INFO
    """Returns format_name, format tuple or None"""
    filename_lc = filename.lower()
    for format_name, format_info in six.iteritems(FORMAT_INFO):
        if filename_lc.endswith(format_info.ext):
            return format_name, format_info
    return None


INPUT_FORMATS = ['ldr', 'mpd']
OUTPUT_FORMATS = ['3ds']

LDRCONVERTER_INPUT_FORMATS = set(('ldr', 'mpd'))
LDRCONVERTER_OUTPUT_FORMATS = set(('3ds',))

# Application initialization
FM = None


def init():
    global FM, INPUT_FORMATS, OUTPUT_FORMATS

    FM = FileManager(app.config["FILE_FOLDER"])

    try:
        status, out, err = run_command([app.config["ASSIMP"], 'listexport'], cwd=FM.tmp_folder)
        have_assimp = True

        if status == 0:
            export_formats = out.split("\n")
            for export_format in export_formats:
                export_format = export_format.strip()
                if not export_format:
                    continue
                status, out, err = run_command([app.config["ASSIMP"], 'exportinfo', export_format], cwd=FM.tmp_folder)
                if status == 0:
                    export_format_info = [s.strip() for s in out.split("\n")]
                    if len(export_format_info) >= 3:
                        export_format_id = export_format_info[0]
                        export_format_ext = export_format_info[1]
                        export_format_descr = export_format_info[2]
                        if export_format_ext.startswith("*."):
                            export_format_ext = export_format_ext[2:]
                        elif export_format_ext.startswith("."):
                            export_format_ext = export_format_ext[1:]
                        export_format_ext = export_format_ext.lower()
                        format_name = export_format_ext

                        format_info = FORMAT_INFO.get(format_name)
                        if format_info:
                            if not format_info.description:
                                format_info.description = export_format_descr
                        else:
                            FORMAT_INFO[format_name] = FileFormat(format_name.upper(),
                                                                  export_format_descr,
                                                                  "application/octet-stream",
                                                                  '.' + export_format_ext)
                        if format_name not in OUTPUT_FORMATS:
                            OUTPUT_FORMATS.append(format_name)

        status, out, err = run_command([app.config["ASSIMP"], 'listext'], cwd=FM.tmp_folder)
        if status == 0:
            import_exts = out.split(';')
            for ext in import_exts:
                format_name = ext.strip().lower()
                if format_name.startswith("*."):
                    my_ext = format_name[1:]
                    format_name = format_name[2:]
                elif format_name.startswith("."):
                    my_ext = format_name
                    format_name = format_name[1:]
                else:
                    my_ext = format_name
                format_info = FORMAT_INFO.get(format_name, None)
                if not format_info:
                    format_info = FileFormat(format_name.upper(), format_name.upper() + " File Format",
                                             "application/octet-stream", my_ext)
                    FORMAT_INFO[format_name] = format_info
                if format_name not in INPUT_FORMATS:
                    INPUT_FORMATS.append(format_name)


        #for i in FORMAT_INFO.values():
        #    logger.info(i)

    except OSError as e:
        logger.exception("Could not run assimp")
        have_assimp = False


@app.route("/", methods=['GET'])
def root():
    return render_template("index.html",
                           FORMAT_INFO=FORMAT_INFO,
                           INPUT_FORMATS=INPUT_FORMATS,
                           OUTPUT_FORMATS=OUTPUT_FORMATS)


@app.route("/api/hash/<hash>", methods=["GET"])
def get_file_by_hash(hash):
    global FM

    fentry = FM.fdb.get(hash)
    if fentry is None:
        abort(404)

    attachment_filename = fentry.get('filename', hash)

    file_path = fentry.path
    head, tail = os.path.split(file_path)

    @after_this_request
    def cleanup(response):
        FM.remove_later(fentry)
        return response

    # Send file back
    return send_from_directory(head, tail, as_attachment=True, attachment_filename=attachment_filename)


class FileGuard(object):
    def __init__(self, fd, name):
        self.fd = fd
        self.name = name
        self.file = None

    def __repr__(self):
        return "FileGuard({!r}, {!r})".format(self.fd, self.name)

    @classmethod
    def mkstemp(cls, *args, **kwargs):
        fd, name = tempfile.mkstemp(*args, **kwargs)
        return cls(fd, name)

    def open(self, *args, **kwargs):
        if self.fd is not None:
            file = os.fdopen(self.fd, *args, **kwargs)
            self.release_descriptor()
        else:
            file = open(self.name, *args, **kwargs)
        return file

    def release_descriptor(self):
        fd = self.fd
        self.fd = None
        return fd

    def close_descriptor(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def swap(self, other):
        assert isinstance(other, FileGuard)
        self.fd, other.fd = other.fd, self.fd
        self.name, other.name = other.name, self.name

    def release(self):
        name = self.name
        self.name = None
        return name

    def close(self):
        self.close_descriptor()
        if self.name is not None:
            os.unlink(self.name)
            self.name = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class ConversionError(Exception):
    def __init__(self, message, stdout=None, stderr=None, oserror=None):
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        self.oserror = oserror
        super(ConversionError, self).__init__(message)


@app.errorhandler(ConversionError)
def conversion_error(error):
    if error.oserror is not None:
        status = 500  # Internal Server Error
    else:
        status = 400  # Bad Request
    return error_response(error.message, status)


def ldr_convert(input_file, output_file):
    args = [app.config["LDRCONVERT"],
            '-v',
            input_file.name,
            output_file.name]

    env = {
        'LDRAWDIR': app.config['LDRAWDIR']
    }

    commandline = args
    try:
        status, out, err = run_command(commandline, env=env, cwd=FM.tmp_folder)
    except OSError as e:
        message = 'Could not execute command line "{}" in directory "{}": {}'.format(
            ' '.join(commandline), FM.tmp_folder, e)
        logger.exception(message)
        raise ConversionError(message=message, oserror=e)
    if status != 0:
        raise ConversionError(message='Conversion failed', stdout=out, stderr=err)
    input_file.close()
    return output_file


def assimp_convert(input_file, output_file):
    args = [app.config["ASSIMP"],
            'export',
            input_file.name,
            output_file.name]

    commandline = args
    try:
        status, out, err = run_command(commandline, cwd=FM.tmp_folder)
    except OSError as e:
        message = 'Could not execute command line "{}" in directory "{}": {}'.format(
            ' '.join(commandline), FM.tmp_folder, e)
        logger.exception(message)
        raise ConversionError(message=message, oserror=e)
    if status != 0:
        raise ConversionError(message='Conversion failed', stdout=out, stderr=err)
    input_file.close()
    return output_file


@app.route("/api/convert/<input_format_name>/<output_format_name>", methods=["GET", "POST"])
def convert(input_format_name, output_format_name):
    global FM
    global FORMAT_INFO

    uri = None
    uri_path = None
    data = None

    if request.method == "GET":
        uri = request.args.get('uri', None)
        if uri is None:
            return error_response('Error: no URI specified', status_code=400)
        uri_path = urlparse(uri).path
    elif request.method == "POST":
        if not request.data:
            return error_response("Data missing in POST request")
        data = request.data
    else:
        return error_response("Bad request")

    if input_format_name == 'auto' and uri_path:
        result = derive_format(uri_path)
        if result:
            input_format_name, input_format = result
        else:
            return error_response('Could not derive input file format from URI {}'.format(uri))
    else:
        input_format = FORMAT_INFO.get(input_format_name)
        if not input_format:
            return error_response('Unsupported source format {}'.format(input_format_name))

    output_format = FORMAT_INFO.get(output_format_name)
    if not output_format:
        return error_response('Unsupported destination format {}'.format(output_format_name))

    get_hash = request.args.get('get_hash', None) in ('1', 'true')

    if uri_path:
        head, tail = os.path.split(uri_path)
        prefix, suffix = os.path.splitext(tail)
    else:
        prefix = 'output'
        suffix = input_format.ext

    with FileGuard.mkstemp(dir=FM.tmp_folder, prefix=prefix, suffix=suffix) as input_file:

        if uri:
            logger.info("Download URI {} to file {}".format(uri, input_file.name))

            try:
                response = requests.get(uri, stream=True)
            except requests.RequestException as e:
                logger.exception("HTTP Request Error")
                return error_response("HTTP Request Error: {}".format(e))

            try:
                with input_file.open('wb') as file:
                    for block in response.iter_content(1024):
                        file.write(block)
                    file.flush()
            except requests.HTTPError as e:
                logger.exception("HTTP Error")
                return error_response("HTTP Error: {}".format(e))
        elif data:
            with input_file.open('wb') as file:
                file.write(data)

        logger.info("Converting file from format {} to format {}".format(input_format.name, output_format.name))

        use_ldrconverter = input_format_name in LDRCONVERTER_INPUT_FORMATS
        use_assimp_converter = not use_ldrconverter or output_format_name not in LDRCONVERTER_OUTPUT_FORMATS

        output_file = FileGuard.mkstemp(dir=FM.tmp_folder, prefix=prefix, suffix=output_format.ext)
        try:

            tmp_file = None
            try:
                if use_ldrconverter:
                    if output_format_name not in LDRCONVERTER_OUTPUT_FORMATS:
                        tmp_file = FileGuard.mkstemp(dir=FM.tmp_folder, prefix=prefix, suffix='.3ds')
                        ldr_convert(input_file, tmp_file)
                        input_file.swap(tmp_file)
                    else:
                        ldr_convert(input_file, output_file)

                if use_assimp_converter:
                    assimp_convert(input_file, output_file)

            finally:
                if tmp_file:
                    tmp_file.close()

            if get_hash:
                hash = hash_file(output_file.name)
                output_file.close_descriptor()
                fentry = FM.fdb.get_or_create(hash, move_from=output_file.name,
                                              data={'filename': prefix + output_format.ext})
                output_file.release()
                return jsonify({'hash': hash})
            else:
                head, tail = os.path.split(output_file.name)
                file_for_removal = output_file.release()

                @after_this_request
                def cleanup(response):
                    FM.remove_later(file_for_removal)
                    return response

                # Send file back
                return send_from_directory(head, tail, as_attachment=True)
        finally:
            output_file.close()

    return error_response(
        message='Error: Conversion from {} format to {} format is unsupported'.format(input_format.name,
                                                                                      output_format.name),
        status_code=501)
