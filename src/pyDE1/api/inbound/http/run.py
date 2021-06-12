"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import multiprocessing, multiprocessing.connection
import time

from email.utils import formatdate  # RFC2822 dates

from pyDE1.de1.exceptions import *

# Right now, this is all "sync" processing. As it is a benefit to only have
# one request pending at a time, this shouldn't be a big problem.
# Going to async for the "second half" of waiting for the response
# might be a way to provide a timeout and prevent permanent blocking.


def run_api_inbound(api_pipe: multiprocessing.connection.Connection):

    SERVER_ROOT = '/'
    PATCH_SIZE_LIMIT = 4096

    import logging
    import sys

    logger = logging.getLogger(multiprocessing.current_process().name)
    logger.info(
        f"Inbound ran: id {id(sys.modules)}")

    from pyDE1.dispatcher.mapping import MAPPING

    # cpn = multiprocessing.current_process().name
    # for k in sys.modules.keys():
    #     if (k.startswith('pyDE1')
    #             or k.startswith('bleak')
    #             or k.startswith('asyncio-mqtt')):
    #         print(
    #             f"{cpn}: {k}"
    #         )

    import http.server
    import json

    from http import HTTPStatus

    from pyDE1.dispatcher.resource import Resource
    from pyDE1.dispatcher.payloads import APIRequest, APIResponse, HTTPMethod
    from pyDE1.dispatcher.validate import validate_patch

    class RequestHandler (http.server.BaseHTTPRequestHandler):

        def do_GET(self):
            timestamp = time.time()

            try:
                resource = Resource(self.path.removeprefix(SERVER_ROOT))
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

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.GET,
                             resource=resource,
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
                resource = Resource(self.path.removeprefix(SERVER_ROOT))
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
                validate_patch(resource=resource, patch=patch)
            except (json.JSONDecodeError, DE1APIError) as exception:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes(repr(exception), 'utf-8'))
                return

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.PATCH,
                             resource=resource,
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

    server = http.server.HTTPServer(('localhost', 1234),
                                    RequestHandler)
    server.serve_forever()
