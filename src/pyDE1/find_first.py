"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Quick-and-dirty, WET, find first DE1 or Skale
Scale finde will eventually check subclasses of Scale with
cls.device_adv_is_recognized_by()
"""

import asyncio
import logging
import traceback

from typing import Optional

from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

import pyDE1.default_logger

logger = logging.getLogger('Scanner')

async def stop_scanner_if_running(scanner: BleakScanner):
    logger = logging.getLogger('StopScanner')
    try:
        scanning = scanner.is_scanning
    except AttributeError:  # On Linux
        scanning = None
    if scanning:
        logger.info(f"Is scanning")
        await scanner.stop()
    elif scanning is None:
        logger.info(f"is_scanning returned None")
        try:
            await scanner.stop()
            logger.info(f"Scanner stopped")
        except KeyError:
            logger.info("Ignoring KeyError on scanner stop")
    else:
        logger.info(f"NOT scanning")


async def find_first_skale(timeout=5.0) -> BleakClient:

    scanner = BleakScanner(timeout=timeout)
    skale_client: Optional[BleakClient] = None
    found_skale = asyncio.Event()

    def is_skale(device: BLEDevice, adv: AdvertisementData):

        nonlocal skale_client

        if found_skale.is_set():
            # logger.info(f"Skipping adv from {device} as already found skale")
            return
        if adv.local_name and adv.local_name.startswith('Skale'):
            found_skale.set()
            try:
                skale_client = BleakClient(device)
            except KeyError:
                logger.warning(
                    "Fallback to address on KeyError, "
                    "likely from metadata: {}\n{}".format(
                        device.metadata,
                        traceback.format_exc(),
                    ))
                skale_client = BleakClient(device.address)
            logger.info(f"Scale at {skale_client.address}")

    scanner.register_detection_callback(is_skale)

    logger.info("Scan start")
    await scanner.start()

    logger.info("Waiting for Skale adv")
    try:
        await asyncio.wait_for(found_skale.wait(), timeout=timeout)
        logger.info("Found")
    except asyncio.TimeoutError:
        logger.info("Not found")

    await stop_scanner_if_running(scanner)
    return skale_client


async def find_first_de1(timeout=5.0) -> BleakClient:

    scanner = BleakScanner(timeout=timeout)
    de1_client: Optional[BleakClient] = None
    found_de1 = asyncio.Event()

    def is_de1(device: BLEDevice, adv: AdvertisementData):

        nonlocal de1_client

        if found_de1.is_set():
            # logger.info(f"Skipping adv from {device} as already found DE1")
            return
        if adv.local_name and adv.local_name.startswith('DE1'):
            found_de1.set()
            try:
                de1_client = BleakClient(device)
            except KeyError:
                logger.warning(
                    "Fallback to address on KeyError, "
                    "likely from metadata: {}\n{}".format(
                        device.metadata,
                        traceback.format_exc(),
                    ))
                de1_client = BleakClient(device.address)
            logger.info(f"DE1 at {de1_client.address}")

    scanner.register_detection_callback(is_de1)

    logger.info("Scan start")
    await scanner.start()

    logger.info("Waiting for DE1 adv")
    try:
        await asyncio.wait_for(found_de1.wait(), timeout=timeout)
        logger.info("Found")
    except asyncio.TimeoutError:
        logger.info("Not found")

    await stop_scanner_if_running(scanner)
    return de1_client

