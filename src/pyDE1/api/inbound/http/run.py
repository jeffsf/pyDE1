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

import pyDE1.config
from pyDE1.exceptions import *


# Right now, this is all "sync" processing. As it is a benefit to only have
# one request pending at a time, this shouldn't be a big problem.
# Going to async for the "second half" of waiting for the response
# might be a way to provide a timeout and prevent permanent blocking.


def run_api_inbound(config: pyDE1.config.Config,
                    log_queue: multiprocessing.Queue,
                    api_pipe: mpc.Connection):

    import asyncio
    import http.server
    import json
    import os
    import re
    import time

    from email.utils import formatdate  # RFC2822 dates
    from http import HTTPStatus
    from traceback import TracebackException
    from typing import Optional, Union, NamedTuple, Dict, Pattern

    import pyDE1
    import pyDE1.pyde1_logging as pyde1_logging
    import pyDE1.shutdown_manager as sm

    from pyDE1.dispatcher.mapping import MAPPING, mapping_requires
    from pyDE1.dispatcher.resource import Resource
    from pyDE1.dispatcher.payloads import APIRequest, APIResponse, HTTPMethod
    from pyDE1.dispatcher.validate import validate_patch_return_targets
    # These two needed as they have specific fields that need to be unpickled
    from pyDE1.exceptions import (
        DE1APIUnsupportedStateTransitionError, DE1APIUnsupportedFeatureError
    )
    from pyDE1.supervise import SupervisedTask, SupervisedExecutor
    from pyDE1.utils import timestamp_to_str_with_ms


    logger = pyDE1.getLogger('Inbound')

    pyde1_logging.setup_queue_logging(config.logging, log_queue)
    pyde1_logging.config_logger_levels(config.logging)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    def on_shutdown_underway_cleanup():
        logger.info("Watching for shutdown event")
        sm.shutdown_underway.wait()
        logger.info("Shutting down HTTP server")
        try:
            server.shutdown()
        except (NameError, AttributeError):
            pass
        logger.info("Setting cleanup_complete")
        sm.cleanup_complete.set()

    on_shutdown_wait_task = loop.run_in_executor(
        None, on_shutdown_underway_cleanup)

    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    loop.set_exception_handler(sm.exception_handler)

    async def heartbeat():
        hlog = pyDE1.getLogger('Heartbeat.InboundAPI')
        while True:
            await asyncio.sleep(10)
            hlog.debug("===== BOOP =====")

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

    MIME_TYPE_MAP = {
        '.txt': 'text/plain',
        '.log': 'text/plain',
        '.json': 'application/json',
        '.zip': 'application/zip',
        '.gz': 'application/gz',
        '.bz2': 'application/x-bzip2',
        '.xz': 'application/x-xz',
    }

    MIME_TYPE_DEFAULT = 'application/octet-stream'

    class FileDetails(NamedTuple):
        id: str
        name: str  # Redundant
        size: int
        atime: float
        mtime: float
        ctime: float

    def file_detail_list(dirname: str):
        if not os.path.isdir(dirname):
            raise DE1TypeError(
                f"Apparent misconfiguration as '{dirname}' "
                "is not a directory")
        retval = []
        with os.scandir(dirname) as dir_entries:
            for dir_entry in dir_entries:
                dir_entry: os.DirEntry
                if not dir_entry.is_file():
                    continue
                dir_entry_stat = dir_entry.stat()
                details = FileDetails(
                    id=dir_entry.name,
                    name=dir_entry.name,
                    size=dir_entry_stat.st_size,
                    atime=dir_entry_stat.st_atime,
                    mtime=dir_entry_stat.st_mtime,
                    ctime=dir_entry_stat.st_ctime
                )
                retval.append(details._asdict())
        return retval

    # TODO: This should somehow be "automated" and driven off Resource

    resources_with_params: Dict[Resource, Pattern] = {
        Resource.LOG: re.compile('^log/(?P<id>[a-zA-Z0-9._-]+)$')
    }

    class RequestHandler (http.server.BaseHTTPRequestHandler):

        def __init__(self, *args, **kwargs):
            # Calling super().__init__() starts processing, set up logger first
            self._start = time.time()
            self._logger = pyDE1.getLogger('Inbound.HTTP')
            super(RequestHandler, self).__init__(*args, **kwargs)

        def _format_log_message(self, fmt, *args) -> str:
            # No need for CLF here
            dt = (time.time() - self._start) * 1000
            return "%.0f %s %s" % (dt,
                                   fmt % args,
                                   self.address_string())

        def log_message(self, fmt, *args):
            self._logger.info(self._format_log_message(fmt, *args))

        def log_error(self, fmt, *args):
            self._logger.error(self._format_log_message(fmt, *args))

        def log_request(self, code='-', size='-'):
            if isinstance(code, HTTPStatus):
                code = f'{code.value} "{code.phrase}"'
            self.log_message('%s %s %s',
                             str(code), str(size), self.requestline)

        def send_error_response(self,
                                code: Union[HTTPStatus, int], resp_str: str,
                                timestamp: Optional[float] = None):
            if timestamp is None:
                timestamp = time.time()
            resp_bytes = resp_str.encode('utf-8')
            self.send_response(code)
            self.send_header("Content-type", "text/plain")
            self.send_header("Content-length", str(len(resp_bytes)))
            self.send_header("Last-Modified", formatdate(timestamp,
                                                         localtime=True))
            self.end_headers()
            self.wfile.write(resp_bytes)

        def get_resource(self) -> (Optional[Resource], Dict):
            self._logger.info(f"Request: {self.requestline}")
            resource: Optional[Resource] = None
            parameter_dict = {}
            code = None
            resp_str = ''
            root_relative = remove_prefix(self.path, config.http.SERVER_ROOT)
            try:
                # resource = Resource(self.path.removeprefix(SERVER_ROOT))
                resource = Resource(root_relative)
            except ValueError:
                for res, pattern in resources_with_params.items():
                    res: Resource
                    pattern: Pattern
                    match = pattern.match(root_relative)
                    if match is not None:
                        resource = res
                        parameter_dict = match.groupdict()
                    break

            if resource is None:
                code = HTTPStatus.NOT_FOUND
                resp_str = f"Unrecognized resource {self.requestline}"

            elif ((self.command == "GET" and not resource.can_get)
                  or (self.command == "PATCH" and not resource.can_patch)
                  or (self.command == "PUT" and not resource.can_put)
                  or (self.command == "POST" and not resource.can_post)
                  or (self.command == "DELETE" and not resource.can_delete)
                  or self.command not in (
                          'GET', 'PATCH', 'PUT', 'POST', 'DELETE')):
                code = HTTPStatus.METHOD_NOT_ALLOWED
                resp_str = f"{self.command} not permitted for {resource}"

            if code is not None:
                self.send_error_response(code, resp_str)

            return resource, parameter_dict

        # NB: This does not support Transfer-encoding: chunked
        def get_content(self) -> Optional[Union[bytes, bytearray, str]]:

            content = None
            content_length = self.headers.get('content-length')

            if content_length is None:
                self.send_error_response(
                    HTTPStatus.LENGTH_REQUIRED,
                    "Missing Content-Length header")
                return None

            else:
                content_length = int(content_length)


            this_content_limit = config.http.PATCH_SIZE_LIMIT
            try:
                resource = Resource(
                    remove_prefix(self.path, config.http.SERVER_ROOT))
                if resource == Resource.DE1_FIRMWARE:
                    this_content_limit = 1 * 1024 * 1024  # FW1258 < 500 kB
            except ValueError:
                pass

            if content_length > this_content_limit:
                self.send_error_response(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "Patch is too large")

            else:
                if content_length > 0:
                    content = self.rfile.read(content_length)
                else:
                    content = ''

            return content

        def queue_and_respond(self, req: APIRequest):

            api_pipe.send(req)

            # In the sync world, nothing in parallel in this process
            # so might as well just block, rather than craziness

            readable = api_pipe.poll(timeout=config.http.RESPONSE_TIMEOUT)
            if readable:
                resp = api_pipe.recv()
            else:
                e = TimeoutError(
                    "Timeout waiting for response from controller, "
                    f"over {config.http.RESPONSE_TIMEOUT} sec")
                resp = APIResponse(
                    timestamp=time.time(),
                    original_timestamp=req.timestamp,
                    payload=None,
                    exception=e,
                    tbe=TracebackException.from_exception(e)
                )

            self.process_response(resp)

        # Split as some requests are handled in this process directly
        def process_response(self, resp: APIResponse,
                             mime_type: 'str' = "application/json"):

            if resp.exception is None:
                content = resp.payload
                if mime_type.endswith('/json') and not isinstance(content, str):
                    content = json.dumps(content,
                                          sort_keys=True, indent=4) + "\n"
                if isinstance(content, str):
                    content = content.encode('utf-8')

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-type", mime_type)
                self.send_header("Content-length", str(len(content)))
                self.send_header("Last-Modified", formatdate(resp.timestamp,
                                                             localtime=True))
                self.end_headers()
                self.wfile.write(content)

            else:

                body = ''.join(resp.tbe.format())

                if isinstance(resp.exception,
                              (DE1DBNoMatchingRecord,)):
                    http_status = HTTPStatus.NOT_FOUND

                elif isinstance(resp.exception,
                              (DE1APIUnsupportedStateTransitionError,
                               DE1NotConnectedError,
                               DE1IsConnectedError,
                               DE1NoAddressError,
                               DE1OperationInProgressError,)):
                    http_status = HTTPStatus.CONFLICT

                elif isinstance(resp.exception,
                                DE1APIUnsupportedFeatureError):
                    http_status = HTTPStatus.IM_A_TEAPOT

                elif isinstance(resp.exception, DE1APIError):
                    http_status = HTTPStatus.BAD_REQUEST

                elif isinstance(resp.exception,
                                (TimeoutError,
                                 asyncio.exceptions.TimeoutError)):
                    http_status = HTTPStatus.REQUEST_TIMEOUT

                else:
                    http_status = HTTPStatus.INTERNAL_SERVER_ERROR

                self.send_error_response(code=http_status,
                                         resp_str=body,
                                         timestamp=resp.timestamp)

            rtt = (time.time() - resp.original_timestamp) * 1000
            self._logger.debug(
                f"RTT: {rtt:0.1f} ms {self.requestline}"
            )
            return

        def do_GET(self):

            timestamp = time.time()
            (resource, parameter_dict) = self.get_resource()
            if resource is None:
                return

            if resource == Resource.LOGS:
                payload = None
                exc = None
                tbe = None
                try:
                    payload = file_detail_list(config.logging.LOG_DIRECTORY)
                except Exception as e:
                    exc = e
                    tbe = TracebackException.from_exception(e)

                resp = APIResponse(
                    original_timestamp=timestamp,
                    timestamp=time.time(),
                    payload=payload,
                    exception=exc,
                    tbe=tbe)

                self.process_response(resp)

            elif resource == Resource.LOG:

                payload = None
                exc = None
                tbe = None

                # TODO: Another ugly combination of id with filename
                filename = os.path.join(config.logging.LOG_DIRECTORY,
                                        parameter_dict['id'])

                try:
                    with open(filename, 'rb') as log_file:
                        payload = log_file.read()
                except Exception as e:
                    exc = e
                    tbe = TracebackException.from_exception(e)

                resp = APIResponse(
                    original_timestamp=timestamp,
                    timestamp=time.time(),
                    payload=payload,
                    exception=exc,
                    tbe=tbe)

                mime_type = MIME_TYPE_DEFAULT
                for suffix, mime_for_suffix in MIME_TYPE_MAP.items():
                    if filename.endswith(suffix):
                        mime_type = mime_for_suffix
                        break

                self.process_response(resp, mime_type)

            else:

                # Not actionable here as connectivity is unknown
                requires = mapping_requires(MAPPING[resource])

                req = APIRequest(timestamp=timestamp,
                                 method=HTTPMethod.GET,
                                 resource=resource,
                                 connectivity_required=requires,
                                 payload=None)

                self.queue_and_respond(req)

            return

        def do_PATCH(self):

            timestamp = time.time()
            (resource, parameter_dict) = self.get_resource()
            if resource is None:
                return

            content = self.get_content()
            if content is None:
                self.send_error_response(
                    HTTPStatus.BAD_REQUEST,
                    "No content provided for PATCH request"
                )
                return

            try:
                patch = json.loads(content)
                targets = validate_patch_return_targets(resource=resource,
                                                        patch=patch)

            except (json.JSONDecodeError, DE1APIError) as exception:
                self.send_error_response(
                    HTTPStatus.BAD_REQUEST,
                    repr(exception))
                return

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.PATCH,
                             resource=resource,
                             connectivity_required=targets,
                             payload=patch)

            self.queue_and_respond(req)
            return

        def do_PUT(self):

            timestamp = time.time()
            (resource, parameter_dict) = self.get_resource()
            if resource is None:
                return

            if resource not in (Resource.DE1_PROFILE,
                                Resource.DE1_PROFILE_ID,
                                Resource.DE1_FIRMWARE,
                                Resource.DE1_FIRMWARE_CANCEL):
                self.send_error_response(
                    HTTPStatus.NOT_IMPLEMENTED,
                    f"PUT not yet supported for {resource}"
                )
                return

            content = self.get_content()
            if content is None:
                self.send_error_response(
                    HTTPStatus.BAD_REQUEST,
                    "No content provided for PUT request"
                )
                return

            try:
                if resource in (Resource.DE1_PROFILE,
                                Resource.DE1_FIRMWARE,
                                Resource.DE1_FIRMWARE_CANCEL,
                                ):
                    patch = content
                else:
                    patch = json.loads(content)
                targets = validate_patch_return_targets(resource=resource,
                                                        patch=patch)

            except (json.JSONDecodeError, DE1APIError) as exception:
                self.send_error_response(
                    HTTPStatus.BAD_REQUEST,
                    repr(exception))
                return

            req = APIRequest(timestamp=timestamp,
                             method=HTTPMethod.PATCH,
                             resource=resource,
                             connectivity_required=targets,
                             payload=patch)

            self.queue_and_respond(req)
            return

    # try:
    server = http.server.HTTPServer((config.http.SERVER_HOST,
                                     config.http.SERVER_PORT),
                                    RequestHandler)

    # Not clear why execution continues even with
    #   OSError: [Errno 98] Address already in use

    # As this may be a restart, ensure that there are not pending responses
    while api_pipe.poll():
        got = api_pipe.recv()
        try:
            from_str = f" from{timestamp_to_str_with_ms(got.timestamp)}"
        except AttributeError:
            from_str = ''
        logger.warning(f"Flushing stale response{from_str}: {got}")

    SupervisedExecutor(None, server.serve_forever)

    loop.run_forever()
