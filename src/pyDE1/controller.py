"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import multiprocessing, multiprocessing.connection
import time


def run_controller(request_pipe: multiprocessing.connection.Connection,
                   response_pipe: multiprocessing.connection.Connection,
                   outbound_pipe: multiprocessing.connection.Connection,):

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    loop.create_task(controller(
        request_pipe=request_pipe,
        response_pipe=response_pipe,
        outbound_pipe=outbound_pipe,
    ))

    loop.run_forever()


async def controller(
        request_pipe: multiprocessing.connection.Connection,
        response_pipe: multiprocessing.connection.Connection,
        outbound_pipe: multiprocessing.connection.Connection,
):

    _shutting_down = False

    loop = asyncio.get_running_loop()

    import logging
    logger = logging.getLogger(multiprocessing.current_process().name)

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    initialize_default_logger()
    set_some_logging_levels()

    import signal

    from pyDE1.de1.c_api import MMR0x80LowAddr, API_MachineStates
    from pyDE1.utils import cancel_tasks_by_name

    from pyDE1.de1 import DE1
    from pyDE1.event_manager import SubscribedEvent

    from pyDE1.de1.ble import CUUID

    from pyDE1.shot_file import CombinedShotLogger

    from pyDE1.scale import AtomaxSkaleII
    from pyDE1.scale.processor import ScaleProcessor
    from pyDE1.flow_sequencer import FlowSequencer

    from pyDE1.find_first import find_first_de1, find_first_skale

    from pyDE1.dispatcher.dispatcher import register_read_pipe_to_queue, \
        start_request_queue_processor, start_response_queue_processor

    from pyDE1.exceptions import DE1NotConnectedError

    # Create these early to prevent AttributeError if killed early

    de1 = DE1()
    skale = AtomaxSkaleII()

    async def shutdown_signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        nonlocal _shutting_down
        _shutting_down = True
        logger = logging.getLogger('ControllerShutdown')
        logger.info(f"{str(signal)} SHUTDOWN INITIATED")
        logger.info("Terminate API processes")
        t0 = time.time()
        if de1.is_connected and de1.current_state not in (
            API_MachineStates.Sleep,
            API_MachineStates.GoingToSleep,
            API_MachineStates.NoRequest,
        ):
            logger.info("Sleep DE1")
            await de1.sleep()
        logger.info("Disconnect DE1 and Skale")
        await asyncio.gather(
            # TODO: Handle de1 or skale None, as well as connection underway
            #       that then connects after this section
            de1.disconnect(),
            skale.disconnect()
        )
        t1 = time.time()
        logger.info(f"Controller elapsed: {t1 - t0:0.3f} sec")

        # NB:
        loop.stop()

    signals = (
        signal.SIGHUP,
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGTERM,
    )

    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda sig=sig: asyncio.create_task(
                shutdown_signal_handler(sig, loop),
                name=str(sig)))

    logging.getLogger('EventManager').setLevel(logging.INFO)
    logging.getLogger(
        f"{CUUID.StateInfo.__str__()}.Notify").setLevel(logging.DEBUG)


    # ppp(MAPPING)  # Pretty messy, needs to be custom mapped

    request_queue = asyncio.Queue()
    response_queue = asyncio.Queue()

    register_read_pipe_to_queue(
        pipe_to_read=request_pipe,
        queue_to_put=request_queue,
    )

    start_request_queue_processor(request_queue=request_queue,
                                  response_queue=response_queue)

    start_response_queue_processor(
        response_queue=response_queue,
        response_pipe=response_pipe
    )

    SubscribedEvent.outbound_pipe = outbound_pipe

    de1_device = await find_first_de1()
    skale_device = await find_first_skale()

    if de1_device is None or skale_device is None and not _shutting_down:
        logger.error("No DE1 or no Skale, exiting")
        await shutdown_signal_handler(signal.SIGTERM, loop)

    # There's a bug in creating from device on bleak 0.11.0 on macOS

    # TODO: Note that this initialization is order-sensitive
    #       It is failing here as DE1() has been called by
    #       _request_queue_processor
    #       de1 = DE1(de1_device)


    de1.address = de1_device
    skale.address = skale_device

    sp = ScaleProcessor()
    await sp.set_scale(skale)

    # TODO: Clean up the init/add/remove/change of FlowSequencer
    fs = FlowSequencer()
    await fs.set_de1(de1)
    await fs.set_scale_processor(sp)
    shot_logger = CombinedShotLogger()

    await asyncio.gather(
        de1.event_shot_sample_with_volumes_update.subscribe(
            shot_logger.sswvu_subscriber),
        sp.event_weight_and_flow_update.subscribe(
            shot_logger.wafu_subscriber)
    )

    await de1.connect()
    await skale.connect()

    logger.info("Connected")

    await asyncio.sleep(1)
    await asyncio.gather(
        de1.start_standard_read_write_notifiers(),
        de1.start_standard_periodic_notifiers(),
        skale.standard_initialization(),
    )

    await asyncio.gather(
        de1.read_standard_mmr_registers(),
        de1.read_cuuid(CUUID.StateInfo),
    )

    # await de1.idle()

    # all_de1 = json.dumps(await get_resource_to_dict(Resource.DE1, fs))
    # print("DE1 length", len(all_de1))  # -> 1748


    # TODO: This needs to get taken into DE1 class directly
    #       or at least be a non-private method of sending
    logger.info("Waiting for notify ready")
    # TODO: Should this confirm all the notifiers are running?
    #       What about the ones that don't notify?
    await de1._notify_ready()
    logger.info("Notify ready seen")
    logger.info("Kill main process when done, as this is now a child")




