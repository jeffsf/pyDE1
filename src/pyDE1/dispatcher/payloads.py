"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Details of the payloads expected/supplied by each of the references

These should be pickle-able so can be passed between processes
"""

import enum
from traceback import TracebackException

from typing import Optional

from pyDE1.dispatcher.resource import Resource


class HTTPMethod (enum.Enum):

    GET = 'GET'
    PUT = 'PUT'
    PATCH = 'PATCH'

    HEAD = 'HEAD'
    POST = 'POST'
    DELETE = 'DELETE'
    OPTIONS = 'OPTIONS'
    TRACE = 'TRACE'
    CONNECT = 'CONNECT'

    def is_supported(self):
        return self in (
            self.GET,
            self.PUT,
            self.PATCH,
        )


class APIRequest:

    def __init__(self, timestamp: float,
                 method: HTTPMethod,
                 resource: Resource,
                 connectivity_required: dict,
                 payload,
                 ):
        self._timestamp = timestamp
        self._method = method
        self._resource = resource
        self._connectivity_required = connectivity_required
        self._payload = payload

    @property
    def timestamp(self):
        return self._timestamp

    @property
    def method(self):
        return self._method

    @property
    def resource(self):
        return self._resource

    @property
    def connectivity_required(self):
        return self._connectivity_required

    @property
    def payload(self):
        return self._payload


class APIResponse:

    def __init__(self,
                 original_timestamp: float,
                 timestamp: float, payload,
                 exception: Optional[Exception] = None,
                 tbe: Optional[TracebackException] = None):
        self._original_timestamp = original_timestamp
        self._timestamp = timestamp
        self._payload = payload
        self._exception = exception
        self._tbe = tbe

    @property
    def original_timestamp(self):
        return self._original_timestamp

    @property
    def timestamp(self):
        return self._timestamp

    @property
    def payload(self):
        return self._payload

    @property
    def exception(self):
        return self._exception

    @property
    def tbe(self):
        return self._tbe



# Payload can come from the inbound process as empty as a request to be filled
# The inbound process is responsible for JSON conversion and validation
# The main process handles the actual data get/put - so no get/put/patch here

# class Payload:
#
#     _resource: Resource = None
#
#     def __init__(self, http_method: HTTPMethod, payload=None):
#         if not http_method.is_supported():
#             raise DE1ValueError(f"Unsupported HTTP method: {http_method}")
#         self._http_method = http_method
#         self._payload = payload
#         self._validated = False
#
#     # def get(self, dispatcher: Dispatcher):
#     #     raise NotImplementedError
#     #
#     # def put(self, dispatcher: Dispatcher):
#     #     raise NotImplementedError
#     #
#     # def patch(self, dispatcher: Dispatcher):
#     #     raise NotImplementedError
#
#     def as_json(self):
#         work = {k: fix_enums(v) for k, v in self.__dict__.items()
#                 if not k.startswith('_')}
#         return json.dumps(work)
#
#     @property
#     def payload(self):
#         return self._payload
#
#     @payload.setter
#     def payload(self, value):
#         raise NotImplementedError






