# Initialization
from __future__ import print_function
import sys
import time
import hashlib
import mimetypes
import os
import shutil
import threading
import subprocess
import tempfile
import pprint

import requests
from flask import Flask, Response, redirect, url_for, render_template, jsonify, request, \
    send_from_directory, abort, after_this_request
from flask.json import JSONEncoder
from flask_reverse_proxy import ReverseProxied
import six
from six.moves.urllib.parse import urlparse
from werkzeug.utils import secure_filename
from filedb import FileDB, FileEntry
from crossdomain import crossdomain

mimetypes.init()
# Fill mimetypes with common types for the case /etc/mime.types is missing
mimetypes.add_type('image/svg+xml', '.svg')
mimetypes.add_type('image/svg+xml', '.svgz')
mimetypes.add_type('image/png', '.png')
mimetypes.add_type('image/gif', '.gif')
mimetypes.add_type('image/jpeg', '.jpg')
mimetypes.add_type('image/jpeg', '.jpeg')


def run_command(command, env=None, cwd=None):
    """returns triple (returncode, stdout, stderr)"""
    logger.info('Run command {} in env {}, cwd {}'.format(command, env, cwd))
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

    logger.info('Command {} returned code: {}'.format(command, status))
    return status, out, err


def run_command2(command, env=None, cwd=None, get_stdout=True, get_stderr=True):
    """returns triple (returncode, stdout, stderr)
    if get_stdout is False stdout tuple element will be set to None
    if get_stderr is False stderr tuple element will be set to None
    """
    logger.info('Run command {} in env {}, cwd {}'.format(command, env, cwd))

    myenv = {}
    if env is not None:
        for k, v in env.items():
            myenv[str(k)] = str(v)
    env = myenv

    with tempfile.TemporaryFile(suffix='stdout') as tmp_stdout:
        with tempfile.TemporaryFile(suffix='stderr') as tmp_stderr:
            if isinstance(command, list) or isinstance(command, tuple):
                p = subprocess.Popen(command,
                                     stdout=tmp_stdout,
                                     stderr=tmp_stderr,
                                     env=env,
                                     cwd=cwd,
                                     universal_newlines=False)
            else:
                p = subprocess.Popen(command,
                                     stdout=tmp_stdout,
                                     stderr=tmp_stderr,
                                     env=env,
                                     cwd=cwd,
                                     universal_newlines=False,
                                     shell=True)
            status = p.wait()

            if get_stdout:
                tmp_stdout.flush()
                tmp_stdout.seek(0)
                out = tmp_stdout.read()
            else:
                out = None

            if get_stderr:
                tmp_stderr.flush()
                tmp_stderr.seek(0)
                err = tmp_stderr.read()
            else:
                err = None

    logger.info('Command {} returned code: {}'.format(command, status))
    return status, out, err


class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ConversionTask):
            return {'hash': obj.result_hash if obj.is_finished() else None,
                    'taskFinished': obj.is_finished(),
                    'taskStatus': obj.get_status(),
                    'taskAge': obj.age,
                    'taskId': obj.task_id}
        return JSONEncoder.default(self, obj)


# create application
app = Flask(__name__, instance_relative_config=True)
app.wsgi_app = ReverseProxied(app.wsgi_app)
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
        if filename:
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


class Task(object):
    def __init__(self, task_id):
        self._lock = threading.RLock()
        self._task_id = task_id
        self._ts = time.time()

    @property
    def lock(self):
        return self._lock

    @property
    def task_id(self):
        return self._task_id

    @property
    def timestamp(self):
        with self._lock:
            return self._ts

    @property
    def age(self):
        with self._lock:
            return time.time() - self._ts

    def touch(self):
        with self._lock:
            self._ts = time.time()

    def is_expired(self, max_sec=10 * 60):
        with self._lock:
            diff = time.time() - self._ts
            return diff > max_sec

    def is_finished(self):
        return True

    def is_started(self):
        return False

    def is_alive(self):
        return False

    def destroy(self):
        pass


class TaskManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._tasks = {}

    @property
    def lock(self):
        return self._lock

    def get_task(self, id):
        with self._lock:
            return self._tasks.get(id)

    def set_task(self, id, task):
        with self._lock:
            self._tasks[id] = task

    def get_or_set_task(self, new_task):
        with self._lock:
            task = self._tasks.get(new_task.task_id)
            if task is None:
                task = new_task
                self._tasks[new_task.task_id] = new_task
            return task

    def del_task(self, task_or_id, destroy=True):
        with self._lock:
            task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
            task = self._tasks.get(task_id)
            if task:
                del self._tasks[task_id]
                if destroy:
                    task.destroy()

    def del_expired_tasks(self, destroy=True):
        with self._lock:
            expired = []
            for task in six.itervalues(self._tasks):
                if task.is_expired():
                    expired.append(task)
            for task in expired:
                del self._tasks[task.task_id]
                if destroy:
                    task.destroy()


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
    global FM, TM
    FM.sync()
    TM.del_expired_tasks()


HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_INTERNAL_SERVER_ERROR = 500
HTTP_NOT_IMPLEMENTED = 501


def error_response(message, status_code=HTTP_INTERNAL_SERVER_ERROR):
    response = jsonify({'message': message})
    response.status_code = status_code
    return response


def bad_request(message):
    return error_response(message=message, status_code=HTTP_BAD_REQUEST)


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
TM = None


def init():
    global FM, TM, INPUT_FORMATS, OUTPUT_FORMATS

    FM = FileManager(app.config["FILE_FOLDER"])
    TM = TaskManager()

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


                    # for i in FORMAT_INFO.values():
                    #    logger.info(i)

    except OSError as e:
        logger.exception("Could not run assimp")
        have_assimp = False


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
def on_conversion_error(error):
    if error.oserror is not None:
        status = HTTP_INTERNAL_SERVER_ERROR
    else:
        status = HTTP_BAD_REQUEST
    return error_response(error.message, status)


class BadRequestError(Exception):
    def __init__(self, message):
        self.message = message
        super(BadRequestError, self).__init__(message)


@app.errorhandler(BadRequestError)
def on_bad_request_error(error):
    return bad_request(error.message)


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
        status, out, err = run_command2(commandline, env=env, cwd=FM.tmp_folder)
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
        status, out, err = run_command2(commandline, cwd=FM.tmp_folder)
    except OSError as e:
        message = 'Could not execute command line "{}" in directory "{}": {}'.format(
            ' '.join(commandline), FM.tmp_folder, e)
        logger.exception(message)
        raise ConversionError(message=message, oserror=e)
    if status != 0:
        raise ConversionError(message='Conversion failed', stdout=out, stderr=err)
    input_file.close()
    return output_file


class ConversionTask(Task):
    def __init__(self,
                 uri=None,
                 uri_path=None,
                 data=None,
                 input_format_name=None,
                 input_format=None,
                 output_format_name=None,
                 output_format=None,
                 get_hash=False):
        super(ConversionTask, self).__init__(
            self.compute_id(input_format_name=input_format_name,
                            output_format_name=output_format_name,
                            uri=uri,
                            data=data))
        self._thread = None
        self._error = None
        self._status = None

        self.uri = uri
        self.uri_path = uri_path
        self.data = data
        self.input_format_name = input_format_name
        self.input_format = input_format
        self.output_format_name = output_format_name
        self.output_format = output_format
        self.get_hash = get_hash

        self.result_hash = None
        self.result_file_name = None

    @staticmethod
    def compute_id(input_format_name, output_format_name, uri, data):
        hasher = hashlib.sha1()
        hasher.update(input_format_name)
        hasher.update(b'\0')
        hasher.update(output_format_name)
        hasher.update(b'\0')
        if uri:
            hasher.update('uri')
            hasher.update(b'\0')
            hasher.update(uri)
        elif data:
            hasher.update('data')
            hasher.update(b'\0')
            hasher.update(data)
        return hasher.hexdigest()

    def set_error(self, error):
        with self._lock:
            self._error = error

    def get_error(self):
        with self._lock:
            return self._error

    def raise_error(self):
        with self._lock:
            if self._error:
                raise self._error

    def set_status(self, status):
        with self._lock:
            self._status = status

    def get_status(self):
        with self._lock:
            return self._status

    def start(self):
        with self._lock:
            if not self._thread:
                self._thread = threading.Thread(target=self._run)
                self._thread.daemon = 1
                self._thread.start()
            self.touch()

    def is_started(self):
        with self._lock:
            return self._thread is not None

    def is_finished(self):
        with self._lock:
            return self._thread is not None and not self._thread.isAlive()

    def is_alive(self):
        with self._lock:
            return self._thread is not None and self._thread.isAlive()

    def is_expired(self, max_sec=10 * 60):
        if not self.is_finished():
            return False
        return super(ConversionTask, self).is_expired(max_sec)

    def stop(self, timeout=None):
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout=timeout)
            self.touch()
            return thread.isAlive()
        return True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def _run(self):
        global FM

        if self.uri_path:
            head, tail = os.path.split(self.uri_path)
            prefix, suffix = os.path.splitext(tail)
        else:
            prefix = 'output'
            suffix = self.input_format.ext

        with FileGuard.mkstemp(dir=FM.tmp_folder, prefix=prefix, suffix=suffix) as input_file:

            if self.uri:
                logger.info("Download URI {} to file {}".format(self.uri, input_file.name))
                self.set_status('Downloading URI: {}'.format(self.uri))

                try:
                    response = requests.get(self.uri, stream=True)
                except requests.RequestException as e:
                    logger.exception("HTTP Request Error")
                    self.set_error(BadRequestError("HTTP Request Error: {}".format(e)))
                    return

                try:
                    with input_file.open('wb') as file:
                        for block in response.iter_content(1024):
                            file.write(block)
                        file.flush()
                except requests.HTTPError as e:
                    logger.exception("HTTP Error")
                    self.set_error(BadRequestError("HTTP Error: {}".format(e)))
                    return
            elif self.data:
                with input_file.open('wb') as file:
                    file.write(self.data)

            msg = "Converting file from format {} to format {}".format(self.input_format.name, self.output_format.name)
            logger.info(msg)
            self.set_status(msg)

            use_ldrconverter = self.input_format_name in LDRCONVERTER_INPUT_FORMATS
            use_assimp_converter = not use_ldrconverter or self.output_format_name not in LDRCONVERTER_OUTPUT_FORMATS

            output_file = FileGuard.mkstemp(dir=FM.tmp_folder, prefix=prefix, suffix=self.output_format.ext)
            try:

                tmp_file = None
                try:
                    if use_ldrconverter:
                        if self.output_format_name not in LDRCONVERTER_OUTPUT_FORMATS:
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

                if self.get_hash:
                    hash = hash_file(output_file.name)
                    output_file.close_descriptor()
                    fentry = FM.fdb.get_or_create(hash, move_from=output_file.name,
                                                  data={'filename': prefix + self.output_format.ext})
                    output_file.release()
                    self.result_hash = hash
                    return
                else:
                    self.result_file_name = output_file.release()

            finally:
                output_file.close()
                if self.get_error():
                    self.set_status('Conversion failed')
                else:
                    self.set_status('Conversion succeeded')

        def destroy(self):
            global FM

            if self.result_hash:
                fentry = FM.fdb.get(self.result_hash)
                FM.remove_later(fentry)

            if self.result_file_name:
                FM.remove_later(self.result_file_name)


@app.route("/", methods=['GET'])
def root():
    return render_template("index.html",
                           FORMAT_INFO=FORMAT_INFO,
                           INPUT_FORMATS=INPUT_FORMATS,
                           OUTPUT_FORMATS=OUTPUT_FORMATS)


@app.route("/viewer", methods=['GET'])
def viewer():
    return redirect(url_for('static', filename='WebGLViewer/index.html', **request.args))
    # return redirect(url_for('static', filename='Online3DViewer/website/index.html'))


@app.route("/api/hash/<hash>", methods=["GET"])
@crossdomain(origin='*')
def get_file_by_hash(hash):
    global FM

    fentry = FM.fdb.get(hash)
    if fentry is None:
        abort(404)

    attachment_filename = fentry.get('filename', hash)

    file_path = fentry.path
    head, tail = os.path.split(file_path)

    # Send file back
    return send_from_directory(head, tail, as_attachment=True, attachment_filename=attachment_filename)


@app.route("/api/task/<task_id>", methods=["GET"])
def get_task_status(task_id):
    global TM, FM

    conv_task = TM.get_task(task_id)
    if conv_task is None:
        abort(404)

    if conv_task.is_finished():
        conv_task.touch()
        conv_task.stop()
        conv_task.raise_error()

    return jsonify(conv_task)


@app.route("/api/debug/tasks", methods=["GET"])
def debug_get_tasks():
    global TM
    result = []
    with TM.lock:
        for task in six.itervalues(TM._tasks):
            status = None
            task_get_status = getattr(task, 'get_status')
            if callable(task_get_status):
                status = task_get_status()
            result.append({'hash': getattr(task, 'result_hash', None),
                           'taskTimestamp': task.timestamp,
                           'filename': getattr(task, 'result_file_name', None),
                           'taskFinished': task.is_finished(),
                           'taskExpired': task.is_expired(),
                           'taskAge': task.age,
                           'taskStatus': status,
                           'taskId': task.task_id})

    return jsonify(result)


@app.route("/api/convert/<input_format_name>/<output_format_name>", methods=["GET", "POST"])
def convert(input_format_name, output_format_name):
    global FM, FORMAT_INFO, TM

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
            return error_response("Data missing in POST request", status_code=400)
        data = request.data
    else:
        return bad_request("Bad request")

    if input_format_name == 'auto' and uri_path:
        result = derive_format(uri_path)
        if result:
            input_format_name, input_format = result
        else:
            return bad_request('Could not derive input file format from URI {}'.format(uri))
    else:
        input_format = FORMAT_INFO.get(input_format_name)
        if not input_format:
            return bad_request('Unsupported source format {}'.format(input_format_name))

    output_format = FORMAT_INFO.get(output_format_name)
    if not output_format:
        return bad_request('Unsupported destination format {}'.format(output_format_name))

    as_task = request.args.get('as_task', None) in ('1', 'true')
    get_hash = as_task or (request.args.get('get_hash', None) in ('1', 'true'))
    timeout = request.args.get('timeout', None)
    if timeout is not None:
        try:
            timeout = float(timeout)
        except ValueError:
            return bad_request('Invalid timeout parameter: {}'.format(timeout))
        if timeout <= 0:
            timeout = None

    conv_task = TM.get_or_set_task(ConversionTask(uri=uri,
                                                  uri_path=uri_path,
                                                  data=data,
                                                  input_format_name=input_format_name,
                                                  input_format=input_format,
                                                  output_format_name=output_format_name,
                                                  output_format=output_format,
                                                  get_hash=get_hash))
    conv_task.start()

    if as_task:
        if conv_task.is_finished():
            conv_task.touch()
            conv_task.stop()

        return jsonify(conv_task)
    else:
        conv_task.stop()
        conv_task.raise_error()

        if conv_task.result_file_name:
            head, tail = os.path.split(conv_task.result_file_name)
            # Send file back
            return send_from_directory(head, tail, as_attachment=True)
        else:
            return jsonify(conv_task)


@app.route("/api/debug/flask", methods=["GET"])
def list_routes():
    import urllib

    output = []
    output.append('Rules:')
    for rule in app.url_map.iter_rules():

        options = {}
        for arg in rule.arguments:
            options[arg] = "[{0}]".format(arg)

        if rule.methods:
            methods = ','.join(rule.methods)
        else:
            methods = 'GET'
        url = url_for(rule.endpoint, **options)
        line = urllib.unquote("{:50s} {:20s} {}".format(rule.endpoint, methods, url))
        output.append(line)

    output.append('')
    output.append('Request environment:')
    for k, v in six.iteritems(request.environ):
        output.append("{0}: {1}".format(k, pprint.pformat(v, depth=5)))

    return Response('\n'.join(output), mimetype='text/plain')
