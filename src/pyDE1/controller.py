"""
Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

See `manual_setup()` for some still-needed setup on process start
"""

import multiprocessing
import multiprocessing.connection as mpc

import pyDE1.config


def run_controller(master_config: pyDE1.config.Config,
                   log_queue: multiprocessing.Queue,
                   inbound_pipe: mpc.Connection,
                   outbound_pipe: mpc.Connection,
                   database_queue: multiprocessing.Queue):

    pyDE1.config.config = master_config
    from pyDE1.config import config

    import asyncio
    import time

    import pyDE1.pyde1_logging as pyde1_logging
    import pyDE1.shutdown_manager as sm

    from pyDE1.de1 import DE1
    from pyDE1.de1.c_api import API_MachineStates
    from pyDE1.dispatcher.dispatcher import (
        register_read_pipe_to_queue,
        start_request_queue_processor, start_response_queue_processor
    )
    from pyDE1.event_manager import SubscribedEvent
    from pyDE1.flow_sequencer import FlowSequencer
    from pyDE1.scale.processor import ScaleProcessor

    pyde1_logging.setup_queue_logging(config.logging, log_queue)
    pyde1_logging.config_logger_levels(config.logging)

    logger = pyDE1.getLogger('Controller')

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    def on_shutdown_underway_cleanup():
        logger.info("Watching for shutdown event")
        sm.shutdown_underway.wait()

        async def _the_rest():
            t0 = time.time()
            de1 = DE1()

            logger.debug(
                f"DE1 current state: {de1.current_state.__repr__()}")
            if de1.current_state not in (
                    API_MachineStates.Sleep,
                    API_MachineStates.GoingToSleep,
                    API_MachineStates.NoRequest,
            ):
                if de1.is_connected:
                    logger.info("Sleep DE1")
                    await de1.sleep()
                else:
                    logger.warning("Unable to sleep DE1, not connected")
            logger.info(f"Disconnecting devices")
            # for device in _disconnect_set:
            #     await device.disconnect()
            for device in [DE1(), ScaleProcessor().scale]:
                if device is not None:
                    await device.disconnect()
            t1 = time.time()
            logger.info(f"Controller shutdown took {t1 - t0:0.3f} sec")
            logger.info("Setting cleanup_complete")
            sm.cleanup_complete.set()

        asyncio.run_coroutine_threadsafe(_the_rest(), loop)

    on_shutdown_wait_task = loop.run_in_executor(
        None, on_shutdown_underway_cleanup)

    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    loop.set_exception_handler(sm.exception_handler)

    request_queue = asyncio.Queue()
    response_queue = asyncio.Queue()

    register_read_pipe_to_queue(
        pipe_to_read=inbound_pipe,
        queue_to_put=request_queue,
    )

    # In dispatcher, this process "does the work"
    start_request_queue_processor(request_queue=request_queue,
                                  response_queue=response_queue)

    # In dispatcher, moves response from queue to pipe
    start_response_queue_processor(
        response_queue=response_queue,
        response_pipe=inbound_pipe
    )

    # Sets up the destination for events to be sent to outbound (MQTT) API
    SubscribedEvent.outbound_pipe = outbound_pipe
    SubscribedEvent.database_queue = database_queue

    # TODO: This may no longer be robust, make a classmethod to set/get?
    FlowSequencer.database_queue = database_queue

    loop.run_forever()
