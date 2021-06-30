"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

See `manual_setup()` for some still-needed setup on process start
"""

import asyncio
import logging
import multiprocessing
import multiprocessing.connection as mpc
import time


def run_controller(log_queue: multiprocessing.Queue,
                   inbound_pipe: mpc.Connection,
                   outbound_pipe: mpc.Connection):

    import signal

    from pyDE1.de1.c_api import API_MachineStates

    from pyDE1.de1 import DE1
    from pyDE1.de1.ble import CUUID

    from pyDE1.dispatcher.dispatcher import register_read_pipe_to_queue, \
        start_request_queue_processor, start_response_queue_processor

    from pyDE1.supervise import SupervisedTask

    from pyDE1.event_manager import SubscribedEvent

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    initialize_default_logger(log_queue)
    set_some_logging_levels()

    logger = logging.getLogger(multiprocessing.current_process().name)

    logging.getLogger(
        f"{CUUID.StateInfo.__str__()}.Notify").setLevel(logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    _shutting_down = False
    _disconnect_set = set()

    async def shutdown_signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        nonlocal _shutting_down
        _shutting_down = True
        logger = logging.getLogger('ControllerShutdown')
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
        logger.info(f"Disconnecting {_disconnect_set}")
        for device in _disconnect_set:
            await device.disconnect()
        t1 = time.time()
        logger.info(f"Controller elapsed: {t1 - t0:0.3f} sec")

        # NB:
        loop.stop()

    signals = (
        # signal.SIGHUP,
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGTERM,
    )

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda sig=sig: asyncio.create_task(
                shutdown_signal_handler(sig, loop),
                name=str(sig)))

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

    # This needs to be scheduled as the loop isn't running yet
    SupervisedTask(manual_setup, disconnect_set=_disconnect_set)

    loop.run_forever()


async def manual_setup(disconnect_set: set):

    import signal

    from pyDE1.de1 import DE1
    from pyDE1.flow_sequencer import FlowSequencer
    from pyDE1.scale.processor import ScaleProcessor

    from pyDE1.scale import AtomaxSkaleII

    from pyDE1.find_first import find_first_de1, find_first_skale

    from pyDE1.shot_file import CombinedShotLogger

    logger = logging.getLogger('manual_setup')

    # TODO: Externalize
    de1_device = await find_first_de1()
    skale_device = await find_first_skale()

    # TODO: Externalize
    if de1_device is None:
        logger.error("No DE1, exiting")
        signal.raise_signal(signal.SIGTERM)

    # There's a bug in creating from device on at least bleak 0.11.0 on macOS

    # TODO: Externalize
    de1 = DE1()
    de1.address = de1_device

    skale = AtomaxSkaleII()
    skale.address = skale_device

    sp = ScaleProcessor()

    # TODO: Externalize
    await sp.set_scale(skale)

    # TODO: DEBUG related
    shot_logger = CombinedShotLogger()

    # TODO: DEBUG related
    await asyncio.gather(
        de1.event_shot_sample_with_volumes_update.subscribe(
            shot_logger.sswvu_subscriber),
        sp.event_weight_and_flow_update.subscribe(
            shot_logger.wafu_subscriber)
    )

    # This will fail with asyncio.exceptions.TimeoutError
    # await asyncio.gather(
    #     de1.connect(),
    #     skale.connect(),
    # )

    # TODO: Externalize
    disconnect_set.add(de1)
    await de1.connect()
    if skale.address is not None:
        disconnect_set.add(skale)
        await skale.connect()

