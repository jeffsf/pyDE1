import asyncio
import logging


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