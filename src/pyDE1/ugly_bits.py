"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging


async def manual_setup(disconnect_set: set):

    import signal

    from pyDE1.de1 import DE1
    from pyDE1.flow_sequencer import FlowSequencer
    from pyDE1.scale.processor import ScaleProcessor

    from pyDE1.scale.scale import recognized_scale_prefixes, scale_factory

    from pyDE1.scanner import find_first_matching, \
        DiscoveredDevices, DiscoveredDeviceEntry, _registered_ble_prefixes, \
        scan_until_timeout

    from pyDE1.shot_file import CombinedShotLogger

    logger = logging.getLogger('manual_setup')

    # TODO: Externalize
    de1_device = await find_first_matching(('DE1',))
    scale_device = await find_first_matching(recognized_scale_prefixes())


    # TODO: Externalize
    if de1_device is None:
        logger.error("No DE1, exiting")
        # TODO: How can this cause an exit of main if supervised?
        signal.raise_signal(signal.SIGTERM)

    # There's a bug in creating from device on at least bleak 0.11.0 on macOS

    # TODO: Externalize
    de1 = DE1()
    de1.address = de1_device

    if scale_device:
        scale = scale_factory(scale_device)
    else:
        scale = None
        logger.info("No scale_device found")

    sp = ScaleProcessor()

    # TODO: Externalize
    if scale is not None:
        await sp.set_scale(scale)

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
    if scale is not None:
        disconnect_set.add(scale)
        await scale.connect()
