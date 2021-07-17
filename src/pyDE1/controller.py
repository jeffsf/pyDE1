"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

See `manual_setup()` for some still-needed setup on process start
"""

import multiprocessing
import multiprocessing.connection as mpc

from pyDE1.flow_sequencer import FlowSequencer
from pyDE1.scale.processor import ScaleProcessor


def run_controller(log_queue: multiprocessing.Queue,
                   inbound_pipe: mpc.Connection,
                   outbound_pipe: mpc.Connection,
                   database_queue: multiprocessing.Queue):

    import asyncio
    import logging
    import signal
    import time

    # Hopefully this allows using a "local" version
    import inspect  # to determine the source file for manual_setup()
    from pyDE1.ugly_bits import manual_setup

    from pyDE1.de1.c_api import API_MachineStates

    from pyDE1.de1 import DE1
    from pyDE1.de1.ble import CUUID

    from pyDE1.dispatcher.dispatcher import register_read_pipe_to_queue, \
        start_request_queue_processor, start_response_queue_processor

    from pyDE1.supervise import SupervisedTask

    from pyDE1.event_manager import SubscribedEvent

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    from pyDE1.signal_handlers import add_handler_shutdown_signals

    initialize_default_logger(log_queue)
    set_some_logging_levels()

    logger = logging.getLogger(multiprocessing.current_process().name)

    logging.getLogger(
        f"{CUUID.StateInfo.__str__()}.Notify").setLevel(logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    _shutting_down = False
    _disconnect_set = set()

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    async def shutdown_signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        nonlocal _shutting_down
        logger = logging.getLogger('ControllerShutdown')
        if _shutting_down:
            logger.info("Already shutting down")
            return
        _shutting_down = True
        logger.info(f"{str(signal)} SHUTDOWN INITIATED")
        logger.info("Terminate API processes")
        t0 = time.time()
        de1 = DE1()

        if de1.is_connected and de1.current_state not in (
            API_MachineStates.Sleep,
            API_MachineStates.GoingToSleep,
            API_MachineStates.NoRequest,
        ):
            logger.info("Sleep DE1")
            await de1.sleep()
        logger.info(f"Disconnecting devices")
        # for device in _disconnect_set:
        #     await device.disconnect()
        for device in [DE1(), ScaleProcessor().scale]:
            if device is not None:
                await device.disconnect()
        t1 = time.time()
        logger.info(f"Controller elapsed: {t1 - t0:0.3f} sec")

        # NB:
        loop.stop()

    add_handler_shutdown_signals(shutdown_signal_handler)

    request_queue = asyncio.Queue()
    response_queue = asyncio.Queue()

    register_read_pipe_to_queue(
        pipe_to_read=inbound_pipe,
        queue_to_put=request_queue,
    )

    # In dispatcher, "does the work"
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

    FlowSequencer.database_queue = database_queue

    # This needs to be scheduled as the loop isn't running yet
    try:
        SupervisedTask(manual_setup, disconnect_set=_disconnect_set)
        logger.info("Scheduled task for manual_setup() from "
                    f"{inspect.getfile(manual_setup)}")
    except NameError:
        logger.critical(
            'No manual_setup() found. Right now, this is required')

    loop.run_forever()
