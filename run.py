#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
    Web3DConverter
    ~~~~~~~~~~

    Web Service for LDRConverter

    :copyright: (c) 2016 German Research Center for Artificial Intelligence (DFKI)
    :author: Dmitri Rubinstein
    :license: GPL, see LICENSE for more details
"""



import logging
from logging.handlers import RotatingFileHandler

# Init default console handler

# LOG_FORMAT = '%(asctime)s %(message)s'
LOG_FORMAT = '%(asctime)s %(levelname)s %(pathname)s:%(lineno)s: %(message)s'
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger = logging.getLogger()
logger.addHandler(console_handler)

import os.path
import signal
import sys
import argparse
import copy
import app


def signal_term_handler(signal, frame):
    logger.info('Got signal {}, exiting'.format(signal))
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_term_handler)
signal.signal(signal.SIGINT, signal_term_handler)


def set_loggers_level(loggers, level):
    for i in loggers:
        if isinstance(i, logging.Logger):
            lgr = i
        else:
            lgr = logging.getLogger(i)
        lgr.setLevel(level)


if __name__ == "__main__":

    def ensure_value(namespace, name, value):
        if getattr(namespace, name, None) is None:
            setattr(namespace, name, value)
        return getattr(namespace, name)


    class AppendKeyValue(argparse.Action):

        def __init__(self,
                     option_strings,
                     dest,
                     nargs=None,
                     const=None,
                     default=None,
                     type=None,
                     choices=None,
                     required=False,
                     help=None,
                     metavar=None):
            if nargs == 0:
                raise ValueError('nargs for append actions must be > 0; if arg '
                                 'strings are not supplying the value to append, '
                                 'the append const action may be more appropriate')
            if const is not None and nargs != argparse.OPTIONAL:
                raise ValueError('nargs must be %r to supply const' % argparse.OPTIONAL)
            super(AppendKeyValue, self).__init__(
                option_strings=option_strings,
                dest=dest,
                nargs=nargs,
                const=const,
                default=default,
                type=type,
                choices=choices,
                required=required,
                help=help,
                metavar=metavar)

        def __call__(self, parser, namespace, values, option_string=None):
            kv = values.split('=', 1)
            if len(kv) == 1:
                kv.append('')

            items = copy.copy(ensure_value(namespace, self.dest, []))
            items.append(kv)
            setattr(namespace, self.dest, items)


    class StoreNameValuePair(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            n, v = values.split('=')
            setattr(namespace, n, v)


    print(sys.argv, file=sys.stderr)

    parser = argparse.ArgumentParser(
        prog='run.py',
        description="Run LDRConverter Server.",
        usage="\n%(prog)s [options]")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="enable debug mode")
    parser.add_argument("--debug-http", action="store_true",
                        help="enable HTTP server debug mode")
    parser.add_argument("--use-wsgiref", action="store_true",
                        help="run application with wsgiref server", default=False)
    parser.add_argument("--use-rocket", action="store_true",
                        help="run application with Rocket server", default=False)
    parser.add_argument("-c", "--log-to-console", action="store_true",
                        help="output log to console", default=False)
    parser.add_argument("-p", "--port", action="store", default=8080, type=int,
                        help="server port")
    parser.add_argument("--host", action="store", default="0.0.0.0",
                        help="server host")
    parser.add_argument("--use-debugger", action="store_true",
                        help="enable debugger")
    parser.add_argument("--use-reloader", action="store_true",
                        help="enable reloader")
    parser.add_argument("--config-var", metavar="VAR=VALUE", action=AppendKeyValue,
                        help="set configuration variable: " + ", ".join(
                            ["{}".format(k) for k in list(app.app.config.keys())]))
    parser.add_argument("--version", action="version",
                        version="%(prog)s 0.2")
    # parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)

    args = parser.parse_args(sys.argv[1:])

    debug = args.debug
    use_debugger = args.use_debugger
    use_reloader = args.use_reloader

    handler = None

    # Configure application

    if args.config_var:
        for name, value in args.config_var:
            app.app.config[name] = value

    log_handler = console_handler

    if not args.log_to_console:
        logger.removeHandler(console_handler)
        logfile = app.app.config['LOG_FILE']
        logdir = os.path.dirname(logfile)
        if not os.path.exists(logdir):
            os.makedirs(logdir)
        log_handler = RotatingFileHandler(logfile, maxBytes=40000, backupCount=1)
        if args.debug:
            log_handler.setLevel(logging.DEBUG)
        log_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(log_handler)

    if args.debug:
        # None, , 'werkzeug'
        set_loggers_level((None, app.logger,), logging.DEBUG)

    logger.info('Environment:')
    for k, v in os.environ.items():
        logger.info('%s = %r' % (k, v))
    logger.info('Configuration:')
    for k, v in app.app.config.items():
        logger.info('%s = %r' % (k, v))
    msg = 'app path: "%s"' % (app.app.instance_path)
    logger.info(msg)

    # Initialize application
    logger.info('Initialize application')
    app.init()

    logger.info('Starting application')
    logger.info('Port: %d', args.port)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("once")

        if args.use_wsgiref:
            from wsgiref.simple_server import make_server

            srv = make_server(args.host, args.port, app.app.wsgi_app)
            srv.serve_forever()
        elif args.use_rocket:
            from rocket import Rocket

            log = logging.getLogger('Rocket')
            if args.debug_http:
                log.setLevel(logging.DEBUG)
            log.addHandler(log_handler)

            # Set the configuration of the web server
            server = Rocket(interfaces=(args.host, args.port), method='wsgi',
                            app_info={"wsgi_app": app.app.wsgi_app})


            # Start the Rocket web server
            def rocket_signal_term_handler(signal, frame):
                logger.info('Got signal {}, exiting'.format(signal))
                try:
                    server.stop()
                finally:
                    sys.exit(0)


            signal.signal(signal.SIGTERM, rocket_signal_term_handler)
            signal.signal(signal.SIGINT, rocket_signal_term_handler)

            server.start()
        else:

            if args.debug_http:
                set_loggers_level((None, 'werkzeug'), logging.DEBUG)

            from werkzeug.serving import WSGIRequestHandler


            class CustomRequestHandler(WSGIRequestHandler):
                def connection_dropped(self, error, environ=None):
                    print('dropped {} {}'.format(error, environ))


            app.app.run(debug=args.debug,
                        host=args.host,
                        port=args.port,
                        use_debugger=args.use_debugger,
                        use_reloader=args.use_reloader,
                        threaded=False,
                        request_handler=CustomRequestHandler)
