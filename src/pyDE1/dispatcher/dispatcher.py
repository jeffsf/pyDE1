"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

# Supervise:
#   Task: ResponseQueueProcessor
#   Task: RequestQueueProcessor

import asyncio
import logging
import multiprocessing.connection as mpc
import time
import traceback
from traceback import TracebackException

from pyDE1.de1 import DE1
from pyDE1.exceptions import DE1NotConnectedError, DE1ValueError
from pyDE1.flow_sequencer import FlowSequencer

from pyDE1.dispatcher.resource import Resource
from pyDE1.dispatcher.payloads import APIRequest, APIResponse, HTTPMethod
from pyDE1.dispatcher.implementation import get_resource_to_dict, \
    patch_resource_from_dict
from pyDE1.scale.processor import ScaleProcessor
from pyDE1.supervise import SupervisedTask


QUEUE_TOO_DEEP = 1  # If deeper than this, something is probably wrong, log

logger = logging.getLogger('Dispatcher')


# Interface from multiprocessing (sync) to asyncio.Queue() for async processing

def register_read_pipe_to_queue(
        pipe_to_read: mpc.Connection,
        queue_to_put: asyncio.Queue):
    asyncio.get_event_loop().add_reader(
        pipe_to_read.fileno(),
        _read_pipe_to_queue, pipe_to_read, queue_to_put)


def _read_pipe_to_queue(pipe_to_read: mpc.Connection,
                        queue_to_put: asyncio.Queue):
    data = pipe_to_read.recv()
    queue_to_put.put_nowait(data)
    if (qd := queue_to_put.qsize()) > QUEUE_TOO_DEEP:
        logger.error(
            f"Request queue exceeded QUEUE_TOO_DEEP, {qd} > {QUEUE_TOO_DEEP}")


def start_response_queue_processor(response_queue: asyncio.Queue,
                                   response_pipe: mpc.Connection):
    supervisor = SupervisedTask(
        _response_queue_processor,
        response_queue=response_queue,
        response_pipe=response_pipe)
    return supervisor


async def _response_queue_processor(response_queue: asyncio.Queue,
        response_pipe: mpc.Connection):

    while True:
        response = await response_queue.get()
        response_pipe.send(response)


# Process received APIRequests from the request queue,
# write to the outbound queue.
# TODO: Move the outbound to an asyncio.Queue() later

def start_request_queue_processor(request_queue: asyncio.Queue,
                                  response_queue: asyncio.Queue):
    supervisor = SupervisedTask(
        _request_queue_processor,
        request_queue=request_queue,
        response_queue=response_queue)
    return supervisor


async def _request_queue_processor(request_queue: asyncio.Queue,
                                   response_queue: asyncio.Queue):

    flow_sequencer = FlowSequencer()
    de1 = DE1()
    scale_processor = ScaleProcessor()
    # scale = ScaleProcessor.scale  # No .scale when this starts

    while True:
        got: APIRequest = await request_queue.get()
        logger.debug(f"{got.method.name} {got.resource.name} requires "
                     f"{got.connectivity_required}")
        resource_dict = {}
        exception = None
        tbe = None
        if got.method is HTTPMethod.GET:
            try:
                # TODO: Should be "ready" and not just "connected"
                if (got.connectivity_required['DE1']
                        and not de1.is_connected):
                    raise DE1NotConnectedError("DE1 not connected")
                if (got.connectivity_required['Scale']
                        and (scale_processor.scale is None
                             or not scale_processor.scale.is_connected)):
                    raise DE1NotConnectedError("Scale not connected")
                resource_dict = await get_resource_to_dict(got.resource)
            except Exception as e:
                exception = e
                tbe = TracebackException.from_exception(exception)
                if isinstance(exception, DE1NotConnectedError):
                    level = logging.INFO
                else:
                    level = logging.ERROR
                logger.log(level,
                           f"Exception in processing {got.method} {got.resource}"
                           f" {repr(exception)}")
                logger.log(level,
                           ''.join(tbe.format()))
            response = APIResponse(original_timestamp=got.timestamp,
                                   timestamp=time.time(),
                                   payload=resource_dict,
                                   exception=exception,
                                   tbe=tbe)

        elif got.method is HTTPMethod.PATCH:

            # TODO: Refactor these checks somewhere clearer to API readers
            if got.resource in (Resource.DE1_ID, Resource.SCALE_ID):
                if 'first_if_found' in got.payload:
                    # Only acceptable patch, if present
                    if len(got.payload.keys()) > 1:
                        raise DE1ValueError(
                            f"Use of 'first_if_found' with {got.resource} "
                            f"needs to be exclusive: {got.payload}")

            results_list = None
            try:
                if (got.connectivity_required['DE1']
                        and not de1.is_ready):
                    # Need a pass for setting the DE1 id
                    if (got.resource is Resource.DE1_ID
                        and len(got.payload.keys()) == 1
                        and ('id' in got.payload
                             or 'first_if_found' in got.payload)
                    ):
                        logger.debug("DE1 gets a pass while disconnected")
                    else:
                        raise DE1NotConnectedError("DE1 not connected")

                if (got.connectivity_required['Scale']
                        and (scale_processor.scale is None
                             or not scale_processor.scale.is_ready)):
                    # Need a pass for setting the scale
                    if (got.resource is Resource.SCALE_ID
                        and len(got.payload.keys()) == 1
                        and ('id' in got.payload
                             or 'first_if_found' in got.payload)
                    ):
                        logger.debug("Scale gets a pass while disconnected")
                    else:
                        raise DE1NotConnectedError("Scale not connected")

                results_list = await patch_resource_from_dict(got.resource,
                                                              got.payload)
            except Exception as e:
                exception = e
                tbe = TracebackException.from_exception(exception)
                logger.error(
                    f"Exception in processing {got.method} {got.resource}"
                    f" {repr(exception)}")
                logger.error(''.join(tbe.format()))
            response = APIResponse(original_timestamp=got.timestamp,
                                   timestamp=time.time(),
                                   payload=results_list,
                                   exception=exception,
                                   tbe=tbe)

        elif got.method is HTTPMethod.PUT \
                and got.resource is Resource.DE1_PROFILE:
            results_list = None
            try:
                # TODO: Should be "ready" and not just "connected"
                if (got.connectivity_required['DE1'] and not de1.is_connected):
                    raise DE1NotConnectedError("DE1 not connected")
                if (got.connectivity_required['Scale']
                        and (scale_processor.scale is None
                             or not scale_processor.scale.is_connected)):
                    raise DE1NotConnectedError("Scale not connected")

                # TODO: Implement PUT properly (check for completeness)
                results_list = await patch_resource_from_dict(got.resource,
                                                              got.payload)
            except Exception as e:
                exception = e
                tbe = TracebackException.from_exception(exception)
                logger.error(
                    f"Exception in processing {got.method} {got.resource}"
                    f" {repr(exception)}")
                traceback.print_tb(tbe)
            response = APIResponse(original_timestamp=got.timestamp,
                                   timestamp=time.time(),
                                   payload=results_list,
                                   exception=exception,
                                   tbe=tbe)


        else:
            response = APIResponse(original_timestamp=got.timestamp,
                                   timestamp=time.time(), payload={},
                                   exception=NotImplementedError(
                                       f"{got.method} is not supported"
                                   ))

        response_queue.put_nowait(response)
        if (qd := response_queue.qsize()) > QUEUE_TOO_DEEP:
            logger.error(
                "Response queue exceeded QUEUE_TOO_DEEP, "
                f"{qd} > {QUEUE_TOO_DEEP}")
