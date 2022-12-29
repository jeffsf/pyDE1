"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import enum
import struct
import time

from struct import unpack_from, pack
from typing import Optional, Union, NamedTuple

import pyDE1  # provides getLogger() and that's all
import pyDE1.de1  # Makes imports "work" for stand-alone use
from pyDE1.bledev.managed_bleak_device import ManagedBleakDevice
from pyDE1.config import config
from pyDE1.de1.c_api import API_MachineStates
from pyDE1.event_manager.event_manager import SubscribedEvent
from pyDE1.event_manager.events import DeviceRole
from pyDE1.event_manager.payloads import EventPayload
from pyDE1.lock_logger import LockLogger
from pyDE1.scanner import find_first_matching, RegisteredPrefixes


TIMEOUT_FIRST_UPDATE = 2.5 # seconds after connect


RegisteredPrefixes.add_to_role('BlueDOT', DeviceRole.THERMOMETER)


class BlueDOTUpdate (EventPayload):

    def __init__(self,
                 arrival_time: float,
                 create_time: Optional[float] = None,
                 ):
        super().__init__(arrival_time=arrival_time,
                         create_time=create_time)
        self._version = "1.0.0"
        self.temperature: Optional[float] = None
        self.high_alarm: Optional[float] = None
        self.units: str = "C"
        self.alarm_byte: Optional[Union[bytearray, int]] = None
        self.name: Optional[str] = None


class BDNotification (NamedTuple):
    arrival_time: float
    raw_data: bytearray
    temperature: float
    high_alarm: float
    units: "BDUnit"
    alarm_byte: Union[bytearray, int]


class BDUnit (enum.IntFlag):
    C = 0
    F = 1

    @property
    def freezing(self):
        if self == BDUnit.C:
            return 0
        else:
            return 32


class BlueDOT (ManagedBleakDevice):

    _de1 = pyDE1.de1.DE1()  # To determine if in a steam cycle when connecting

    def __init__(self):

        self._role = DeviceRole.THERMOMETER
        self.logger = pyDE1.getLogger('BlueDOT')
        super().__init__()

        self.updates = SubscribedEvent(self)

        self._last_update: Optional[BDNotification] = None

        self._have_high_alarm = asyncio.Event()  # For beep-on-connect
        
        # CUUID locks
        self._interval_lock = asyncio.Lock()
        self._updates_lock = asyncio.Lock()
        self._high_alarm_lock = asyncio.Lock()
        self._low_alarm_lock = asyncio.Lock()
        self._units_lock = asyncio.Lock()


    @property
    def temperature(self):
        return self._last_update and self._last_update.temperature

    @property
    def units(self):
        return self._last_update and self._last_update.units

    @property
    def high_alarm(self):
        return self._last_update and self._last_update.high_alarm

    @property
    def last_update(self):
        return self._last_update
        
    async def set_updates_on(self, state=True):
        if not self.is_connected:
            self.logger.warning(
                f"Not connected, can't set_updates_on({state})")
            return
        ll = LockLogger(self._updates_lock, 'updates_lock').check()
        async with self._updates_lock:
            ll.acquired()
            if state:
                await self._bleak_client.start_notify(
                    CUUID.UPDATES.uuid,
                    self._notification_callback)
            else:
                await self._bleak_client.stop_notify(CUUID.UPDATES.uuid)
            self.logger.info(f"Notification enabled: {state}")
        ll.released()
        
    async def set_update_rate(self, period: Union[int, float]):
        if not self._bleak_client.is_connected:
            self.logger.warning(
                f"Not connected, can't set_update_rate({period})")
            return
        ll = LockLogger(self._interval_lock, 'interval_lock').check()
        async with self._interval_lock:
            ll.acquired()
            val = int(round(period))
            await self._bleak_client.write_gatt_char(
                CUUID.INTERVAL.uuid, pack('B', val))
            self.logger.info(f"Notification period set to {val}")
        ll.released()

    async def set_high_alarm(self, temperature: Union[int, float]):
        if not self._bleak_client.is_connected:
            self.logger.warning(
                f"Not connected, can't set_high_alarm({temperature})")
            return
        ll = LockLogger(self._high_alarm_lock, 'high_alarm_lock').check()
        async with self._high_alarm_lock:
            ll.acquired()
            val = int(round(temperature))
            try:
                await self._bleak_client.write_gatt_char(
                    CUUID.HIGH_ALARM.uuid, pack('B', val))
                self.logger.info(f"High alarm set: {val}")
            except struct.error as e:
                self.logger.exception(
                    f"Unable to set high alarm for {temperature}",
                    exc_info=e)
        ll.released()

    async def sample_slow(self):
        await self.set_update_rate(60)

    async def sample_normal(self):
        await self.set_update_rate(config.steam.IDLE_SECONDS_PER_SAMPLE)

    async def sample_fast(self):
        await self.set_update_rate(1)

    async def release(self, timeout: Optional[float] = None) -> bool:
        # super().release() doesn't call this class' request_release()
        if self.is_ready:
            await self.sample_slow()
        return await super().release(timeout)

    async def request_release(self):
        if self.is_ready:
            await self.sample_slow()
        await super().request_release()

    # For external API

    async def change_to_id(self, ble_device_id: Optional[str]):
        """
        For now, this won't return until connected or fails to connect
        As a result, will trigger the timeout on API calls
        """
        self.logger.info(f"Request to replace thermometer with {ble_device_id}")

        if ble_device_id == 'scan':
            await self.connect_to_first_if_found()
        else:
            await self.change_address(ble_device_id)

        return self.address

    async def connect_to_first_if_found(self):
        if self.is_connected:
            self.logger.warning(
                "'scan' requested, but already connected. "
                "No action taken.")
        else:
            device = await find_first_matching(DeviceRole.THERMOMETER)
            if device:
                await self.change_address(device)
                await self.capture()
        return self.address

    # From managed_bleak_device, used by external API
    #   address
    #   name
    #   availability_state
    #   availability_setter
    #   device_availability_last_sent

    ###
    ### End of public API
    ###

    # TODO: "make sure" that go_slow() gets called on exit

    async def _initialize_after_connection(self, hold_ready=False):
        self._have_high_alarm.clear()
        self._last_update = None
        await self.set_updates_on()
        # await asyncio.sleep(1)  # Is this needed, and, if so, when?
        await self.sample_fast()
        try:
            await asyncio.wait_for(
                self._have_high_alarm.wait(),
                timeout=TIMEOUT_FIRST_UPDATE)
            # Beep the alarm on getting the update
            old_ha = self._last_update.high_alarm
            new_ha = self._last_update.units.freezing
            await self.set_high_alarm(new_ha)
            await asyncio.sleep(1.0)  # beep time
            await self.set_high_alarm(old_ha)
        except asyncio.TimeoutError:
            self.logger.warning(
                f"Did not get update within {TIMEOUT_FIRST_UPDATE:.1f} sec, "
                "no beep for connection.")
            pass
        if (self._de1.is_ready
                and self._de1.current_state == API_MachineStates.Steam):
            await self.sample_fast()
        else:
            await self.sample_normal()
        self._notify_ready()

    async def _notification_callback(self, sender: int, data: bytearray):

        now = time.time()

        byte_0 = data[0:1].hex()
        (current, high_alarm) = unpack_from('<ii', data, offset=1)
        (units_byte,) = unpack_from('B', data, offset=11)
        byte_12 = data[12:13].hex()
        bluedot_mac = data[13:19]
        alarm_byte = data[19:20]

        # Only used for logging
        last_time = self._last_update.arrival_time if self._last_update else None

        self._last_update = BDNotification(
            arrival_time=now,
            raw_data=data,
            temperature=current,
            high_alarm=high_alarm,
            units=BDUnit(units_byte),
            alarm_byte=alarm_byte,
        )
        self._have_high_alarm.set()

        payload = BlueDOTUpdate(arrival_time=self._last_update.arrival_time)
        payload.temperature = self._last_update.temperature
        payload.high_alarm = self._last_update.high_alarm
        payload.units = self._last_update.units.name
        payload.alarm_byte = self._last_update.alarm_byte
        payload.name = self.name
        await self.updates.publish(payload)

        units_string = BDUnit(units_byte).name
        dt = now - last_time if last_time else 0

        self.logger.debug(
            f"{dt:0.3f} {current} {high_alarm} {units_string} "
            f"{byte_0} {byte_12} {alarm_byte.hex()}")

        

class CUUID (enum.Enum):
    INTERVAL    = '60721D99-6698-4EEC-8E0A-50D0C37F17B9'
    UPDATES     = '783F2991-23E0-4BDC-AC16-78601BD84B39'
    HIGH_ALARM  = 'DE0415CF-D54A-4EA4-A58F-C7AA07F79BAA'
    LOW_ALARM   = 'BFDBEB45-11A3-4406-BCB4-ED7C6F939FBC'
    UNITS       = 'C86CF012-5C33-48AA-82D1-84A57C908CA0'
        
    @property 
    def uuid(self):
        return self.value


if __name__ == "__main__":

    import argparse
    from pyDE1 import pyde1_logging
    from pyDE1.config import config
    import pyDE1.shutdown_manager as sm

    pyde1_logging.setup_initial_logger()

    ap = argparse.ArgumentParser(
        description="""Test the BLueDOT alone.

        """
        f"Default configuration file is at {pyDE1.config.DEFAULT_CONFIG_FILE}"
    )
    ap.add_argument('-c', type=str, help='Use as alternate config file')

    args = ap.parse_args()

    config.load_from_yaml(args.c)

    config.logging.handlers.STDERR = 'DEBUG'
    config.logging.formatters.STDERR = config.logging.formatters.LOGFILE

    pyde1_logging.setup_direct_logging(config.logging)
    pyde1_logging.config_logger_levels(config.logging)

    logger = pyDE1.getLogger('Main')


    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.set_exception_handler(sm.exception_handler)
    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    async def setup_and_run():
        bluetooth_id = '00:a0:50:e2:f6:49'
        bd = BlueDOT()

        # async def wait_for_shutdown():
        #     await sm.wait_for_shutdown_underway()
        #     print("shutdown")
        #     await bd.go_slow()
        #     print("go slow done")
        #     await asyncio.sleep(0.5)
        #     sm.cleanup_complete.set()
        # loop.create_task(wait_for_shutdown())

        await bd.change_address(bluetooth_id)
        await bd.request_capture()
        await bd.event_ready.wait()
        await bd.sample_fast()
        await asyncio.sleep(600)
        await bd.release()
        await asyncio.sleep(5)

    loop.run_until_complete(setup_and_run())