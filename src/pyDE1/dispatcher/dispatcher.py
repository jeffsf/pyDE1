"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import logging
import multiprocessing, multiprocessing.connection
import time

from pyDE1.de1 import DE1
from pyDE1.de1.profile import ProfileByFrames
from pyDE1.de1.exceptions import DE1NotConnectedError
from pyDE1.scale import Scale, AtomaxSkaleII
from pyDE1.flow_sequencer import FlowSequencer

from pyDE1.dispatcher.resource import Resource
from pyDE1.dispatcher.payloads import APIRequest, APIResponse, HTTPMethod
from pyDE1.dispatcher.implementation import get_resource_to_dict, \
    patch_resource_from_dict
from pyDE1.scale.processor import ScaleProcessor

READ_BACK_ON_PATCH = False

QUEUE_TOO_DEEP = 1  # If deeper than this, something is probably wrong, log

logger = logging.getLogger('Dispatcher')


# Interface from multiprocessing (sync) to asyncio.Queue() for async processing

def register_read_pipe_to_queue(
        pipe_to_read: multiprocessing.connection.Connection,
        queue_to_put: asyncio.Queue):
    asyncio.get_event_loop().add_reader(
        pipe_to_read.fileno(),
        _read_pipe_to_queue, pipe_to_read, queue_to_put)


def _read_pipe_to_queue(pipe_to_read: multiprocessing.connection.Connection,
                        queue_to_put: asyncio.Queue):
    data = pipe_to_read.recv()
    queue_to_put.put_nowait(data)
    if (qd := queue_to_put.qsize()) > QUEUE_TOO_DEEP:
        logger.error(
            f"Request queue exceeded QUEUE_TOO_DEEP, {qd} > {QUEUE_TOO_DEEP}")


def start_response_queue_processor(
        response_queue: asyncio.Queue,
        response_pipe: multiprocessing.connection.Connection):
    asyncio.create_task(_response_queue_processor(
        response_queue=response_queue,
        response_pipe=response_pipe),
    name='ResponseQueueProcessor')


async def _response_queue_processor(response_queue: asyncio.Queue,
        response_pipe: multiprocessing.connection.Connection):

    while True:
        response = await response_queue.get()
        response_pipe.send(response)


# Process received APIRequests from the inbound queue,
# write to the outbound queue.
# TODO: Move the outbound to an asyncio.Queue() later

def start_request_queue_processor(request_queue: asyncio.Queue,
                                  response_queue: asyncio.Queue):
    asyncio.create_task(_request_queue_processor(request_queue=request_queue,
                                                 response_queue=response_queue),
                        name='InboundQueueProcessor')


async def _request_queue_processor(request_queue: asyncio.Queue,
                                   response_queue: asyncio.Queue):

    flow_sequencer = FlowSequencer()
    de1 = DE1()
    scale_processor = ScaleProcessor()
    # scale = ScaleProcessor.scale  # No .scale when this starts

    while True:
        got: APIRequest = await request_queue.get()
        print(f"{type(got)}: {got.method} {got.resource} {got.connectivity_required}")
        resource_dict = {}
        exception = None
        if got.method is HTTPMethod.GET:
            try:
                # TODO: Should be "ready" and not just "connected"
                if not de1.is_connected \
                        and got.connectivity_required['DE1']:
                    raise DE1NotConnectedError("DE1 not connected")
                if not scale_processor.scale.is_connected \
                    and got.connectivity_required['Scale']:
                    raise DE1NotConnectedError("Scale not connected")
                resource_dict = await get_resource_to_dict(got.resource)
            except Exception as e:
                exception = e
                logger.error(
                    f"Exception in processing {got.method} {got.resource}"
                    f" {repr(exception)}")
            response = APIResponse(
                original_timestamp=got.timestamp,
                timestamp=time.time(),
                payload = resource_dict,
                exception=exception,
            )

        elif got.method is HTTPMethod.PATCH:
            resource_dict = None
            try:
                # TODO: Should be "ready" and not just "connected"
                if not de1.is_connected \
                        and got.connectivity_required['DE1']:
                    raise DE1NotConnectedError("DE1 not connected")
                if not scale_processor.scale.is_connected \
                    and got.connectivity_required['Scale']:
                    raise DE1NotConnectedError("Scale not connected")
                await patch_resource_from_dict(got.resource,
                                               got.payload)
            except Exception as e:
                exception = e
                logger.error(
                    f"Exception in processing {got.method} {got.resource}"
                    f" {repr(exception)}")
            if READ_BACK_ON_PATCH and \
                    exception is None and got.resource.can_get:
                resource_dict = await get_resource_to_dict(got.resource)
            response = APIResponse(
                original_timestamp=got.timestamp,
                timestamp=time.time(),
                payload = resource_dict,
                exception=exception,
            )

        elif got.method is HTTPMethod.PUT \
                and got.resource is Resource.DE1_PROFILE:
            try:
                # TODO: Should be "ready" and not just "connected"
                if not de1.is_connected \
                        and got.connectivity_required['DE1']:
                    raise DE1NotConnectedError("DE1 not connected")
                if not scale_processor.scale.is_connected \
                    and got.connectivity_required['Scale']:
                    raise DE1NotConnectedError("Scale not connected")

                # TODO: Implement PUT properly (check for completeness)
                await patch_resource_from_dict(got.resource,
                                               got.payload)
            except Exception as e:
                exception = e
                logger.error(
                    f"Exception in processing {got.method} {got.resource}"
                    f" {repr(exception)}")

            response = APIResponse(
                original_timestamp=got.timestamp,
                timestamp=time.time(),
                payload = None,
                exception=exception,
            )


        else:
            response = APIResponse(
                original_timestamp=got.timestamp,
                timestamp=time.time(),
                payload={},
                exception=NotImplementedError(
                    f"{got.method} is not supported"
                ),
            )

        response_queue.put_nowait(response)
        if (qd := response_queue.qsize()) > QUEUE_TOO_DEEP:
            logger.error(
                "Response queue exceeded QUEUE_TOO_DEEP, "
                f"{qd} > {QUEUE_TOO_DEEP}")
