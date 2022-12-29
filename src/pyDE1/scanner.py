"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

# Only one scan can be running at the same time, at least with bleak 0.19
# on BlueZ. Using an exclusive lock can lead to pileups. Should be able
# to support a use case where the user finishes with a choose operation
# and then moves on to the next before the timeout expires.
#
# In a multi-client situation, one user canceling another user's activity
# isn't a great experience, but seems a reasonable compromise here.
#
# Intended behavior is that any new scan cancels any currently running one.
# The cancelled scan sends its scanning:false packet and the new scan sends
# an empty packet to "reset" clients.

import asyncio
import queue
import time

from typing import Iterable, Tuple, Optional

import bleak
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from pyDE1.event_manager.event_manager import SubscribedEvent
from pyDE1.event_manager.events import DeviceRole

import pyDE1
from pyDE1.config import config
from pyDE1.event_manager.payloads import EventPayload
from pyDE1.exceptions import *


logger = pyDE1.getLogger('Bluetooth.Scanner')

# Need an object with a class for the SubscribedEvent
class BluetoothScanner:
    pass

_scan_results_event = SubscribedEvent(BluetoothScanner())
scan_complete = asyncio.Event()


class _RegisteredPrefixes:

    def __init__(self):
        self._prefixes = dict()
        for role in DeviceRole:
            self._prefixes[role]: set[str] = set()
        self.add_to_role('', DeviceRole.UNKNOWN)

    def get_for_role(self, role: DeviceRole):
        if role is None:
            return frozenset()
        else:
            return frozenset(self._prefixes[role])

    def add_to_role(self, prefix: str, role: DeviceRole):
        self._prefixes[role].add(prefix)


RegisteredPrefixes = _RegisteredPrefixes()


# Can't just use nonlocal as it has to be bound in an outer function
# Getting "this module" is reasonably ugly
#   sys.modules[__name__]
#   __import__(__name__)

class _Wrapper:

    def __init__(self):
        self.scanner: Optional[bleak.BleakScanner] = None
        self.role: Optional[DeviceRole] = None
        self.found: list[BLEDevice] = list()
        self.timeout_task: Optional[asyncio.Task] = None

    async def new_run(self,
                scanner: bleak.BleakScanner,
                role: Optional[DeviceRole]=None,
                timeout: Optional[float]=None):
        if timeout is None:
            timeout = config.bluetooth.SCAN_TIME
        self.scanner = None
        self.role = None
        self.found = list()
        self.timeout_task = None
        scan_complete.clear()
        self.scanner = scanner
        self.role = role
        await _scan_results_event.publish(
                    ScanResults(_wrapper.found, role))
        await self.scanner.start()
        self.timeout_task = asyncio.create_task(self._stop_later(timeout))
        self.timeout_task.add_done_callback(
            lambda t: logger.info(
                f"Timeout task done: {t.get_name()}"
                + (" (cancelled)" if t.cancelled() else '')))
        logger.info(f"Scan beginning for {role} {self.timeout_task.get_name()}")

    async def end_run(self):
        # Cancel first, as was not seeming to cancel when done second.
        try:
            self.timeout_task.cancel()
            logger.info(f"Cancelled timeout: {self.timeout_task.get_name()}")
        except AttributeError:
            pass
        try:
            await self.scanner.stop()
            self.scanner = None
            await _scan_results_event.publish(
                ScanResults(self.found, self.role, scanning=False))
            scan_complete.set()
            logger.info(
                f"Scan ended for {self.role}, {len(self.found)} found")
        except AttributeError:
            pass

    async def _stop_later(self, after: float):
        my_scanner = self.scanner
        await asyncio.sleep(after)
        logger.info(
            f"Timeout, stopping scanner: {asyncio.current_task().get_name()}")
        if self.scanner == my_scanner:
            # This is a little dance as calling end_run() will cancel this task
            _wrapper.timeout_task = None
            await self.end_run()
        else:
            logger.warning(
                "Timeout, _stop_later: Stale task "
                + asyncio.current_task().get_name())


_wrapper = _Wrapper()


async def scan_until_timeout(role: DeviceRole = None,
                             timeout = None):

    if timeout is None:
        timeout = config.bluetooth.SCAN_TIME

    loop = asyncio.get_running_loop()

    prefix_set = RegisteredPrefixes.get_for_role(role)

    def check_match(device: BLEDevice, adv: AdvertisementData):
        for prefix in prefix_set:
            if adv.local_name and adv.local_name.startswith(prefix):
                logger.info(
                    f"'{prefix}' matched at {device.address} by {adv}")
                # Can get called more than once if the device data changes
                if device.address not in [d.address
                                          for d in _wrapper.found]:
                    _wrapper.found.append(device)
                loop.create_task(_scan_results_event.publish(
                    ScanResults(_wrapper.found, role)))

    # Cancel any already running
    await _wrapper.end_run()

    scanner = bleak.BleakScanner(detection_callback=check_match)

    try:
        await _wrapper.new_run(scanner, role, timeout)
    except bleak.exc.BleakDBusError as e:
        if e.args[0] == 'org.bluez.Error.InProgress':
            raise DE1OperationInProgressError(e)
        else:
            raise e


async def find_first_matching(role: DeviceRole,
                              timeout=None) -> BLEDevice:

    # Can't use .find_device_by_filter as it is a class method
    # and creates its own

    if timeout is None:
        timeout = config.bluetooth.SCAN_TIME

    loop = asyncio.get_running_loop()

    prefix_set = RegisteredPrefixes.get_for_role(role)

    found_event = asyncio.Event()

    def check_match(device: BLEDevice, adv: AdvertisementData):
        for prefix in prefix_set:
            if adv.local_name and adv.local_name.startswith(prefix):
                logger.info(
                    f"'{prefix}' matched at {device.address} by {adv}")
                _wrapper.found = [device]
                found_event.set()

    async def found_waiter():
        await found_event.wait()
        await _wrapper.end_run()

    # Cancel any already running
    await _wrapper.end_run()

    scanner = bleak.BleakScanner(detection_callback=check_match)

    task_found = asyncio.create_task(found_waiter())

    try:
        await _wrapper.new_run(scanner, role, timeout)
    except bleak.exc.BleakDBusError as e:
        if e.args[0] == 'org.bluez.Error.InProgress':
            raise DE1OperationInProgressError(e)
        else:
            raise e

    # Either found_water or timeout will set scan_complete
    await scan_complete.wait()
    task_found.cancel()
    try:
        return _wrapper.found[-1]
    except IndexError:
        return None



async def scan_from_api(role: DeviceRole):
    await scan_until_timeout(role)


class ScanResults (EventPayload):

    def __init__(self,
                 ble_device_list: list[BLEDevice],
                 role: DeviceRole,
                 scanning: bool = True):
        arrival_time = time.time()
        create_time = arrival_time
        super().__init__(arrival_time, create_time)
        self._version = "1.0.0"
        self.role: DeviceRole = role
        self.scanning = scanning
        if ble_device_list is not None:
            self.devices = [
                {'address': d.address, 'name': d.name, 'rssi': d.rssi}
                for d in ble_device_list ]
        else:
            self.devices = []
