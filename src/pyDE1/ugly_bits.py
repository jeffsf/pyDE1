"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import time

from pyDE1.scale.processor import ScaleProcessor
from pyDE1.scale import recognized_scale_prefixes
from pyDE1.scanner import DiscoveredDevices, find_first_matching


async def manual_setup(disconnect_set: set):

    # DiscoveredDevices()
    # return

    import signal

    from pyDE1.de1 import DE1

    from pyDE1.scanner import scan_from_api

    from pyDE1.shot_file import CombinedShotLogger

    logger = logging.getLogger('manual_setup')

    # Still using internals rather than API, see if can find DE1 and scale

    # logger.info(await scan_from_api(True))
    # await asyncio.sleep(5)
    # logger.info("slept 5 seconds")
    # de1_ble_device = None
    # scale_ble_device = None
    # results = await DiscoveredDevices().devices_seen()
    # for dd in results:
    #     logger.debug(dd.device)
    #     if dd.device.name.startswith('DE1'):
    #         de1_ble_device = dd.device
    #         break
    # for dd in results:
    #     if dd.device.name.startswith('Skale'):
    #         scale_ble_device = dd.device
    #         break

    # sp = ScaleProcessor()
    #
    # t0 = time.time()

    # de1_ble_device = await find_first_matching(('DE1',))
    # scale_ble_device = await find_first_matching(recognized_scale_prefixes())

    de1 = DE1()
    disconnect_set.add(de1)

    # await de1.change_de1_to_id(de1_ble_device.address)
    # await sp.change_scale_to_id(scale_ble_device.address)

    # t1 = time.time()
    # logger.debug(f"##### Connection time: {(t1 - t0):.3f} seconds")

    # if scale_ble_device is not None:
    #     sp = ScaleProcessor()
    #     await sp.change_scale_to_id(scale_ble_device.address)

    # This will fail with asyncio.exceptions.TimeoutError
    # await asyncio.gather(
    #     de1.connect(),
    #     skale.connect(),
    # )


