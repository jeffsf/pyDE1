"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum
import inspect
import time
from typing import (
    Optional, Iterable, NamedTuple, Dict, Set, Tuple, Union,
)

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from pyDE1.bleak_version_check import BLEAK_AFTER_0_17

import pyDE1
from pyDE1.config import config
from pyDE1.event_manager import EventPayload, send_to_outbound_pipes
from pyDE1.exceptions import *
from pyDE1.singleton import Singleton
from pyDE1.supervise import SupervisedTask

logger = pyDE1.getLogger('Bluetooth.Scanner')

# Otherwise will iterate over D,E,1
_registered_ble_prefixes = set()
_registered_ble_prefixes.add('DE1')


class BleakScannerWrapped (BleakScanner):

    def __init__(self, **kwargs):
        super(BleakScannerWrapped, self).__init__(**kwargs)
        self._run_ref = 0

    @property
    def run_id(self):
        """
        This should be considered as opaque by consumers
        """
        return f"{self.__class__.__qualname__}_0x{id(self):x}_{self._run_ref}"

    async def start(self):
        self._run_ref += 1
        logger.debug("Starting scanner")
        ep = ScannerNotification(action=ScannerNotificationAction.STARTED,
                                 run_id=self.run_id)
        await send_to_outbound_pipes(ep)
        await super(BleakScannerWrapped, self).start()

    async def stop(self):
        await super(BleakScannerWrapped, self).stop()
        ep = ScannerNotification(action=ScannerNotificationAction.ENDED,
                                 run_id=self.run_id)
        await send_to_outbound_pipes(ep)
        logger.debug("Stopped scanner")


class ScannerNotificationAction (enum.Enum):
    STARTED = 'started'
    ENDED = 'ended'
    FOUND = 'found'


class ScannerNotification (EventPayload):
    """
    As these don't go through a normal "publish" but are only over MQTT,
    supply a unique ID for this scanning run in run_id so the recipient
    can associate started, found, and ended with a single "run"
    """
    def __init__(self, action: ScannerNotificationAction,
                 run_id: Optional[str] = None,
                 id: Optional[str] = None,
                 name: Optional[str] = None,
                 arrival_time: Optional[float] = None,
                 create_time: Optional[float] = None):
        """
        STARTED and ENDED require None for id and name
        FOUND requires both id and name, though name potentially could be ''
        """
        if arrival_time is None:
            arrival_time = time.time()
        if action in (
                ScannerNotificationAction.STARTED,
                ScannerNotificationAction.ENDED) \
                and (id is not None or name is not None):
            raise DE1TypeError (
                "STARTED and ENDED require None for both id and name")
        if action is ScannerNotificationAction.FOUND \
                and (id is None or name is None):
            raise DE1TypeError (
                "FOUND requires id and name")
        super(ScannerNotification, self).__init__(arrival_time, create_time)
        self._version = '1.0.0'
        self.run_id = run_id
        self.action = action
        self.id = id
        self.name = name


async def notify_bledevice(device: BLEDevice, run_id: Optional[str] = None):
    for prefix in _registered_ble_prefixes:
        if device.name.startswith(prefix):
            ep = ScannerNotification(action=ScannerNotificationAction.FOUND,
                                     id=device.address,
                                     name=device.name,
                                     run_id=run_id)
            asyncio.create_task(send_to_outbound_pipes(ep))
            break


class DiscoveredDeviceEntry (NamedTuple):
    last_seen: float
    device: BLEDevice


class DiscoveredDevices (Singleton):

    def _singleton_init(self, *args, **kwds):
        self._devices_seen: Dict[str, DiscoveredDeviceEntry] = dict()
        self._lock = asyncio.Lock()
        self._queue = asyncio.Queue()
        self._worker = SupervisedTask(self._device_add_queue_worker)

    def add(self, device: BLEDevice, run_id: Optional['str'] = None):
        self._queue.put_nowait(self.AddThis(device=device,
                                            seen_at=time.time(),
                                            run_id=run_id))

    async def devices_seen(self,
                           starts_with_set: Optional[Iterable[str]] = None,
                           bledevice_only=False) \
            -> Set[Union[DiscoveredDeviceEntry, BLEDevice]]:
        # This is going to "lose" active devices as they time out
        async with self._lock:
            retval = set()
            now = time.time()
            pruned = dict()
            for addr, entry in self._devices_seen.items():
                if config.bluetooth.SCAN_CACHE_EXPIRY is not None \
                        and (now - entry.last_seen) \
                            > config.bluetooth.SCAN_CACHE_EXPIRY:
                    pass  # Can't delete in place during iteration
                else:
                    pruned[addr] = entry
            self._devices_seen = pruned

            for addr, entry in self._devices_seen.items():
                include = False
                if starts_with_set is not None:
                    for prefix in starts_with_set:
                        if entry.device.name.startswith(prefix):
                            include = True
                            break
                else:
                    include = True

                if include:
                    if bledevice_only:
                        retval.add(entry.device)
                    else:
                        retval.add(entry)
        return retval

    async def devices_for_json(self):
        retval = list()
        for entry in await self.devices_seen(
                starts_with_set=_registered_ble_prefixes,
                bledevice_only=False):
            retval.append({
                'id': entry.device.address,
                'name': entry.device.name,
                'discovered': entry.last_seen
            })
        return retval

    def ble_device_from_id(self, id: str) -> Optional[BLEDevice]:
        try:
            ble_device = self._devices_seen[id].device
        except KeyError:
            ble_device = None
        return ble_device

    async def clear(self):
        async with self._lock:
            self._devices_seen.clear()

    async def _device_add_queue_worker(self):
        while True:
            add_this = await self._queue.get()
            # Filtering is done in notify_bledevice
            asyncio.create_task(notify_bledevice(device=add_this.device,
                                                 run_id=add_this.run_id))
            async with self._lock:
                self._devices_seen[add_this.device.address] \
                    = DiscoveredDeviceEntry(last_seen=add_this.seen_at,
                                            device=add_this.device)

    class AddThis (NamedTuple):
        device: BLEDevice
        seen_at: float
        run_id: str


async def stop_scanner_if_running(scanner: BleakScanner):
    logger = pyDE1.getLogger('Bluetooth.Scanner')
    logger.debug(f"Stopping {scanner}")
    await scanner.stop()
    logger.debug(f"Stopped {scanner}")
    # try:
    #     scanning = scanner.is_scanning
    # except AttributeError:  # On Linux
    #     scanning = None
    # if scanning:
    #     logger.info(f"Is scanning")
    #     await scanner.stop()
    # elif scanning is None:
    #     logger.info(f"is_scanning returned None")
    #     try:
    #         await scanner.stop()
    #         logger.info(f"Scanner stopped")
    #     except KeyError:
    #         logger.info("Ignoring KeyError on scanner stop")
    # else:
    #     logger.info(f"NOT scanning")


async def find_first_matching(prefix_set: Iterable[str],
                              timeout=None) -> BLEDevice:

    if timeout is None:
        timeout = config.bluetooth.SCAN_TIME

    if isinstance(prefix_set, str):
        raise DE1TypeError(
            "Prefix set of type str will iterate the characters. "
            "('DE1',) is better")

    scanner = BleakScannerWrapped()
    run_id = scanner.run_id
    dd = DiscoveredDevices()

    def is_match(device: BLEDevice, adv: AdvertisementData) -> bool:
        nonlocal run_id, dd

        dd.add(device=device, run_id=run_id)
        retval = False
        for prefix in prefix_set:
            if adv.local_name and adv.local_name.startswith(prefix):
                logger.info(
                    f"'{prefix}' matched at {device.address} "
                    f"by {adv}")
                retval = True
        return retval

    if BLEAK_AFTER_0_17:
        fdbf = await scanner.find_device_by_filter(filter_func=is_match)
    else:
        fdbf = await scanner.find_device_by_filter(filterfunc=is_match)

    return fdbf


async def scan_until_timeout(timeout=None) -> Tuple[BleakScannerWrapped,
                                                    float,
                                                    asyncio.Event]:
    """
    Returns (scanner, timeout, event) where event will be set
    once timeout expires and scanner stops
    """

    if timeout is None:
        timeout = config.bluetooth.SCAN_TIME

    def add_to_dd(device: BLEDevice, adv: AdvertisementData) -> None:
        nonlocal dd, scanner
        dd.add(device=device, run_id=scanner.run_id)

    scanner = BleakScannerWrapped(detection_callback=add_to_dd)
    event = asyncio.Event()
    dd = DiscoveredDevices()

    async def stop_later(after: float):
        nonlocal scanner, event
        await asyncio.sleep(after)
        await scanner.stop()
        event.set()

    await scanner.start()
    asyncio.create_task(stop_later(timeout))

    return scanner, timeout, event


async def scan_from_api(timeout: Optional[Union[int, float, bool]]=None):
    if timeout is True:
        logger.warning(
            "Passing true for 'begin' is deprecated. "
            "Pass a timeout in seconds or null to accept the default")
    elif timeout is False:
        logger.warning(
            "Passing false for 'begin' is deprecated. "
            "Pass a timeout in seconds or null to accept the default.")
        return None
    elif timeout <= 0:
        raise DE1ValueError(
            f"Timeout must be greater than zero {timeout}")

    (scanner, timeout, event) = await scan_until_timeout(timeout=timeout)
    return {
        'run_id': scanner.run_id,
        'timeout': timeout
    }
