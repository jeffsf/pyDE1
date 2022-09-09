"""
Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum
import logging
import sys
import time
from typing import Callable

import pyDE1
from pyDE1.scale import Scale
from pyDE1.scale.events import ScaleWeightUpdate, ScaleButtonPress

logger = pyDE1.getLogger('Scale.AtomaxSkaleII')


class AtomaxSkaleII(Scale):

    def __init__(self):
        super(AtomaxSkaleII, self).__init__()
        self._nominal_period = 0.1  # seconds per sample
        self._minimum_tare_request_interval = 2.5 * self._nominal_period
        self._sensor_lag = 0.38  # seconds, including all transit delays
        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"

        # Enable tare on button 1, hold UUID if need to unsubscribe
        self._button_1_tare_subscriber_id = None
        self._supervisor_button = asyncio.create_task(
            self._subscribe_button_press())

        # Linux, at least on an RPi 3B, needs response=True for write_gatt_char
        self._write_gatt_char_response = sys.platform == 'linux'

    async def standard_initialization(self, hold_notification=False):
        await super(AtomaxSkaleII, self).standard_initialization(
            hold_notification=True)
        await self.set_grams()
        if not hold_notification:
            await self._notify_ready()

    async def update_self_from_device(self):
        self._model_number = await self._bleak_client.read_gatt_char(
            Characteristic.MODEL_NUMBER.cuuid)
        self._fw_revision = await self._bleak_client.read_gatt_char(
            Characteristic.FW_REVISION.cuuid)
        self._hw_revision = await self._bleak_client.read_gatt_char(
            Characteristic.HW_REVISION.cuuid)
        self._sw_revision = await self._bleak_client.read_gatt_char(
            Characteristic.SW_REVISION.cuuid)
        self._manufacturer_name = await self._bleak_client.read_gatt_char(
            Characteristic.MANUFACTURER_NAME.cuuid)

    async def start_sending_weight_updates(self):
        await self._bleak_client.start_notify(
            Characteristic.WEIGHT_NOTIFY_EF81.cuuid,
            self._create_weight_update_hander())
        logger.info("Sending weight updates")

    async def stop_sending_weight_updates(self):
        await self._bleak_client.stop_notify(
            Characteristic.WEIGHT_NOTIFY_EF81.cuuid)
        logger.info("Stopped weight updates")

    def is_sending_weight_updates(self):
        return NotImplementedError

    async def _tare_internal(self):
        await self.send_command(Command.TARE)
        logger.info("Internal tare sent")

    async def current_weight(self):
        # await self._bleak_client.read_gatt_char(
        #     Characteristic.UNKNOWN_EF83.uuid)
        # # That CUUID doesn't look like weight
        return None

    async def display_on(self):
        await self.send_command(Command.DISPLAY_WEIGHT)
        await self.send_command(Command.DISPLAY_ON)
        logger.info("Display on")

    async def display_off(self):
        await self.send_command(Command.DISPLAY_OFF)
        logger.info("Display off")

    async def set_grams(self):
        await self.send_command(Command.GRAMS)
        logger.info("Grams selected")

    @property
    def supports_button_press(self):
        return True

    async def start_sending_button_updates(self):
        await self._bleak_client.start_notify(
            Characteristic.BUTTON_NOTIFY_EF82.cuuid,
            self._create_button_press_hander())
        logger.info("Sending button updates")

    async def stop_sending_button_updates(self):
        await self._bleak_client.stop_notify(
            Characteristic.BUTTON_NOTIFY_EF82.cuuid)
        logger.info("Stopped button updates")

    async def send_command(self, command: "Command"):
        await self._bleak_client.write_gatt_char(command.cuuid, command.value,
            response=self._write_gatt_char_response)

    def _create_weight_update_hander(self) -> Callable:
        scale = self
        local_logger = logger

        async def weight_update_handler(sender, data):
            nonlocal scale, local_logger

            try:
                now = time.time()

                w1 = int.from_bytes(data[1:4], byteorder='little',
                                    signed=True) / 10.0
                w2 = int.from_bytes(data[5:8], byteorder='little',
                                    signed=True) / 10.0
                # if w1 == w2:
                #     print(f"{dt:8.6f} {w1}")
                # else:
                #     print(f"{dt:8.6f} {w1}  {w2}")

                self._update_scale_time_estimator(now)

                await scale.event_weight_update.publish(
                    ScaleWeightUpdate(
                        arrival_time=now,
                        scale_time=self._scale_time_from_latest_arrival(now),
                        weight=w1
                    ))
            except Exception as e:
                local_logger.exception(e)
                raise e

        return weight_update_handler

    def _create_button_press_hander(self) -> Callable:
        scale = self

        async def button_press_handler(sender, data):
            nonlocal scale

            now = time.time()
            b = data[0]
            sbp = ScaleButtonPress(arrival_time=now, button=b)
            await scale.event_button_press.publish(sbp)

        return button_press_handler

    async def _subscribe_button_press(self):
        scale = self

        async def button_1_tare(sbp: ScaleButtonPress) -> None:
            nonlocal scale
            if sbp.button == 1:
                await scale.tare()
                logger.info("Button 1 - Tare requested")

        self._button_1_tare_subscriber_id \
            = await self._event_button_press.subscribe(button_1_tare)
        

class Characteristic(enum.Enum):

    CONFIGURATION_EF80 =    'ef80'  # W
    WEIGHT_NOTIFY_EF81 =    'ef81'  # N
    BUTTON_NOTIFY_EF82 =    'ef82'  # N
    UNKNOWN_EF83 =          'ef83'  # R

    BATTERY_LEVEL =         '2a19'  # 0-63

    MODEL_NUMBER =          '2a24'  # "SkaleII"

    FW_REVISION =           '2a26'
    HW_REVISION =           '2a27'
    SW_REVISION =           '2a28'
    MANUFACTURER_NAME =     '2a29'  # "ATOMAX INC."

    UNKNOWN =               '0f050002-3225-44b1-b97d-d3274acb29de'  # R

    @property
    def cuuid(self):
        return f"0000{self.value}-0000-1000-8000-00805f9b34fb"


# These typically get written to CONFIGURATION_EF80
class Command(enum.Enum):

    DISPLAY_WEIGHT = b'\xec'
    DISPLAY_ON = b'\xed'
    DISPLAY_OFF = b'\xee'

    OUNCES = b'\x02'
    GRAMS = b'\x03'
    PERSIST_UNITS = b'\04'

    TARE = b'\x10'

    TIMER_ZERO = b'\xd0'
    TIMER_START = b'\xd1'
    TIMER_STOP = b'\xd2'

    # Place cal weight on Skale, send command
    CALIBRATE_500G = b'\xca\x05'
    CALIBRATE_1000G = b'\xca\x0a'

    # Undocumented at this time
    FILTER_WEAK = b'\x09\x00'
    FILTER_DEFAULT = b'\x09\x01'
    FILTER_STRONG = b'\x09\x02'
    FILTER_STRONGER = b'\x09\x03'

    @property
    def cuuid(self):
        return Characteristic.CONFIGURATION_EF80.cuuid


Scale.register_constructor(AtomaxSkaleII, 'Skale')