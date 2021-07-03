"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

# Supervise:
#   Task: loop.run_in_executor(None, server.serve_forever)


import multiprocessing
import multiprocessing.connection as mpc
import time

from email.utils import formatdate  # RFC2822 dates

from pyDE1.exceptions import *

# Right now, this is all "sync" processing. As it is a benefit to only have
# one request pending at a time, this shouldn't be a big problem.
# Going to async for the "second half" of waiting for the response
# might be a way to provide a timeout and prevent permanent blocking.
from pyDE1.supervise import SupervisedTask, SupervisedExecutor


def run_api_inbound(log_queue: multiprocessing.Queue,
                    api_pipe: mpc.Connection):

    from pyDE1.config.http import SERVER_HOST, SERVER_PORT, SERVER_ROOT, \
        PATCH_SIZE_LIMIT

    import logging
    import multiprocessing

    logger = logging.getLogger(multiprocessing.current_process().name)

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    initialize_default_logger(log_queue)
    set_some_logging_levels()

    from pyDE1.dispatcher.mapping import MAPPING, mapping_requires

    # cpn = multiprocessing.current_process().name
    # for k in sys.modules.keys():
    #     if (k.startswith('pyDE1')
    #             or k.startswith('bleak')
    #             or k.startswith('asyncio-mqtt')):
    #         print(
    #             f"{cpn}: {k}"
    #         )

    import asyncio
    import http.server
    import json
    import multiprocessing
    import signal

    from http import HTTPStatus

    # This one is needed as it has specific fields that need to be unpickled
    from pyDE1.exceptions import DE1APIUnsupportedStateTransitionError, \
        DE1APIUnsupportedFeatureError

    from pyDE1.dispatcher.resource import Resource
    from pyDE1.dispatcher.payloads import APIRequest, APIResponse, HTTPMethod
    from pyDE1.dispatcher.validate import validate_patch_return_targets

    from pyDE1.utils import cancel_tasks_by_name

    from pyDE1.signal_handlers import add_handler_shutdown_signals

    logger = logging.getLogger(multiprocessing.current_process().name)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    async def shutdown_signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        logger = logging.getLogger('HTTPShutdown')
        logger.info(f"{str(signal)} SHUTDOWN INITIATED")
        logger.info("Shutting down HTTP server")
        server.shutdown()
        logger.info("Shutting down other tasks")
        cancel_tasks_by_name('', starts_with=True)
        logger.info("Stopping loop")
        loop.stop()
        logger.info("Loop stopped, closing this process")
        # AttributeError: 'NoneType' object has no attribute 'kill'
        # multiprocessing.current_process().kill()
        multiprocessing.current_process().close()
        logger.info("Process closed")

    add_handler_shutdown_signals(shutdown_signal_handler)

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            logger.info("===== BOOP =====")

    SupervisedTask(heartbeat)

    try:
        str.removeprefix  # Python 3.9 and later

        def remove_prefix(string: str, prefix: str) -> str:
            return string.removeprefix(prefix)

    except AttributeError:

        def remove_prefix(string: str, prefix: str) -> str:
            if string.startswith(prefix):
                return string[len(prefix):]
            else:
                return string


    class RequestHandler (http.server.BaseHTTPRequestHandler):

        def do_GET(self):
            timestamp = time.time()

            try:
                # resource = Resource(self.path.removeprefix(SERVER_ROOT))
                resource = Resource(remove_prefix(self.path, SERVER_ROOT))
            except ValueError:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes('Unrecognized resource\n', 'utf-8'))
                return

            if not resource.can_get:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes('GET not permitted', 'utf-8'))
                return

            # Not actionable here as connectivity is unknown
            requires = mapping_requires(MAPPING[resource])

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.GET,
                             resource=resource,
                             connectivity_required=requires,
                             payload=None)

            api_pipe.send(req)

            # TODO: This should be async or otherwise to provide a timeout
            resp: APIResponse = api_pipe.recv()

            if resp.exception is None:
                resp_str = json.dumps(resp.payload,
                                      sort_keys=True, indent=4) + "\n"
                resp_bytes = resp_str.encode('utf-8')

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Content-length", str(len(resp_bytes)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(resp_bytes)

            elif isinstance(resp.exception, DE1NotConnectedError):
                #
                # TODO: Include the stack trace and all
                #
                body = repr(resp.exception).encode('utf-8')
                self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-length", str(len(body)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(body)

            else:
                body = repr(resp.exception).encode('utf-8')
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-length", str(len(body)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(body)

            logger.debug(
                f"RTT: {(time.time() - timestamp) * 1000:0.1f} ms"
            )
            return

        """
        curl -X PATCH --data '{"name": "new name"}' \
        -H "content-type: application/json" \
        http://localhost:NNNN/path/to/resource
        
        or 
        
        --data @filename.json
        """

        # NB: This does not support Transfer-encoding: chunked

        def do_PATCH(self):

            timestamp = time.time()

            try:
                # resource = Resource(self.path.removeprefix(SERVER_ROOT))
                resource = Resource(remove_prefix(self.path, SERVER_ROOT))
            except ValueError:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes('Unrecognized resource\n', 'utf-8'))
                return

            if not resource.can_patch:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes('PATCH not permitted', 'utf-8'))
                return

            content_length = int(self.headers.get('content-length'))
            if content_length is None:
                self.send_response(HTTPStatus.LENGTH_REQUIRED)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(
                    "Missing Content-Length header".encode('utf-8'))
                return

            if content_length > PATCH_SIZE_LIMIT:
                self.send_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write("Patch is too large".encode('utf-8'))
                return

            content = self.rfile.read(content_length)

            try:
                patch = json.loads(content)
                targets = validate_patch_return_targets(resource=resource,
                                                        patch=patch)
            except (json.JSONDecodeError, DE1APIError) as exception:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes(repr(exception), 'utf-8'))
                return

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.PATCH,
                             resource=resource,
                             connectivity_required=targets,
                             payload=patch)

            api_pipe.send(req)

            # TODO: This should be async or otherwise to provide a timeout

            resp: APIResponse = api_pipe.recv()

            if resp.exception is None:
                resp_str = json.dumps(resp.payload,
                                      sort_keys=True, indent=4) + "\n"
                resp_bytes = resp_str.encode('utf-8')

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Content-length", str(len(resp_bytes)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(resp_bytes)

            else:
                body = repr(resp.exception).encode('utf-8')

                if isinstance(resp.exception,
                              DE1APIUnsupportedStateTransitionError):
                    http_status = HTTPStatus.CONFLICT

                elif isinstance(resp.exception,
                                DE1APIUnsupportedFeatureError):
                    http_status = HTTPStatus.IM_A_TEAPOT

                elif isinstance(resp.exception, DE1APIError):
                    http_status = HTTPStatus.BAD_REQUEST

                else:
                    http_status = HTTPStatus.INTERNAL_SERVER_ERROR

                self.send_response(http_status)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-length", str(len(body)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(body)

            logger.debug(
                f"RTT: {(time.time() - timestamp) * 1000:0.1f} ms"
            )
            return

        # NB: This does not support Transfer-encoding: chunked

        def do_PUT(self):

            timestamp = time.time()

            try:
                # resource = Resource(self.path.removeprefix(SERVER_ROOT))
                resource = Resource(remove_prefix(self.path, SERVER_ROOT))
            except ValueError:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes('Unrecognized resource\n', 'utf-8'))
                return

            if not resource.can_put:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes('PUT not permitted', 'utf-8'))
                return

            if not resource is Resource.DE1_PROFILE:
                self.send_response(HTTPStatus.NOT_IMPLEMENTED)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes(
                    f'PUT not yet supported beyond {Resource.DE1_PROFILE}',
                    'utf-8'))
                return

            content_length = int(self.headers.get('content-length'))
            if content_length is None:
                self.send_response(HTTPStatus.LENGTH_REQUIRED)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(
                    "Missing Content-Length header".encode('utf-8'))
                return

            if content_length > PATCH_SIZE_LIMIT:
                self.send_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write("Patch is too large".encode('utf-8'))
                return

            content = self.rfile.read(content_length)

            try:
                if resource in (Resource.DE1_PROFILE,
                                Resource.DE1_FIRMWARE):
                    patch = content
                else:
                    patch = json.loads(content)
                targets = validate_patch_return_targets(resource=resource,
                                                        patch=patch)
            except (json.JSONDecodeError, DE1APIError) as exception:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes(repr(exception), 'utf-8'))
                return

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.PATCH,
                             resource=resource,
                             connectivity_required=targets,
                             payload=patch)

            api_pipe.send(req)

            # TODO: This should be async or otherwise to provide a timeout

            resp: APIResponse = api_pipe.recv()

            if resp.exception is None:
                resp_str = json.dumps(resp.payload,
                                      sort_keys=True, indent=4) + "\n"
                resp_bytes = resp_str.encode('utf-8')

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Content-length", str(len(resp_bytes)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(resp_bytes)

            else:
                body = repr(resp.exception).encode('utf-8')

                if isinstance(resp.exception,
                              DE1APIUnsupportedStateTransitionError):
                    http_status = HTTPStatus.CONFLICT

                elif isinstance(resp.exception,
                                DE1APIUnsupportedFeatureError):
                    http_status = HTTPStatus.IM_A_TEAPOT

                elif isinstance(resp.exception, DE1APIError):
                    http_status = HTTPStatus.BAD_REQUEST

                else:
                    http_status = HTTPStatus.INTERNAL_SERVER_ERROR

                self.send_response(http_status)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-length", str(len(body)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(body)

            logger.debug(
                f"RTT: {(time.time() - timestamp) * 1000:0.1f} ms"
            )
            return

    server = http.server.HTTPServer((SERVER_HOST, SERVER_PORT),
                                    RequestHandler)

    supervisor_server = SupervisedExecutor(None, server.serve_forever)

    loop.run_forever()

