"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import enum
import sys
import time

import pyDE1
from pyDE1.scale.events import ScaleWeightUpdate, ScaleButtonPress
from pyDE1.scale.generic_scale import register_scale_class, GenericScale

logger = pyDE1.getLogger('Scale.AtomaxSkaleII')


@register_scale_class
class AtomaxSkaleII (GenericScale):

    _supports_prefixes = ['Skale']

    def __init__(self):
        super(AtomaxSkaleII, self).__init__()
        self._adopt_sync()

    def _adopt_sync(self):
        self._nominal_period = 0.1  # seconds per sample
        self._minimum_tare_request_interval = 2.5 * self._nominal_period
        self._sensor_lag = 0.38  # seconds, including all transit delays
        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"

        # Enable tare on button 1, hold UUID if need to unsubscribe
        self._button_1_tare_subscriber_id = None
        self._task_button_press = asyncio.create_task(
            self._subscribe_button_press())

        # Linux, at least on an RPi 3B, needs response=True for write_gatt_char
        self._write_gatt_char_response = (sys.platform == 'linux')

    async def _adopt_class(self):
        self._adopt_sync()

    async def _leave_class(self):
        try:
            self._task_button_press.cancel()
        except AttributeError:
            pass
        await self._event_button_press.unsubscribe(
            self._button_1_tare_subscriber_id)
        for attr in (
            '_write_gatt_char_response',
            '_button_1_tare_subscriber_id',
            '_task_button_press',
        ):
            delattr(self, attr)

    async def _initialize_after_connection(self, hold_ready=False):
        await super(AtomaxSkaleII, self)._initialize_after_connection(
            hold_ready=True)
        await self.set_grams()
        if not hold_ready:
            self._notify_ready()

    async def start_sending_weight_updates(self):
        await self._bleak_client.start_notify(
            Characteristic.WEIGHT_NOTIFY_EF81.cuuid,
            self._weight_update_handler)
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
            self._button_press_handler)
        logger.info("Sending button updates")

    async def stop_sending_button_updates(self):
        await self._bleak_client.stop_notify(
            Characteristic.BUTTON_NOTIFY_EF82.cuuid)
        logger.info("Stopped button updates")

    async def send_command(self, command: "Command"):
        await self._bleak_client.write_gatt_char(
            command.cuuid,
            command.value,
            response=self._write_gatt_char_response)

    async def _update_self_from_device(self):
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

    async def _weight_update_handler(self, sender, data):

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

            await self.event_weight_update.publish(
                ScaleWeightUpdate(
                    arrival_time=now,
                    scale_time=self._scale_time_from_latest_arrival(now),
                    weight=w1
                ))
        except Exception as e:
            logger.exception(e)
            raise e

    async def _button_press_handler(self, sender, data):

        now = time.time()
        b = data[0]
        sbp = ScaleButtonPress(arrival_time=now, button=b)
        await self.event_button_press.publish(sbp)

    async def _button_press_subscriber(self, sbp: ScaleButtonPress) -> None:
        if sbp.button == 1:
            await self.tare()
            logger.info("Button 1 - Tare requested")

    async def _subscribe_button_press(self):
        self._button_1_tare_subscriber_id \
            = await self._event_button_press.subscribe(
            self._button_press_subscriber)
        self._task_button_press = None


class Characteristic(enum.Enum):
    CONFIGURATION_EF80 = 'ef80'  # W
    WEIGHT_NOTIFY_EF81 = 'ef81'  # N
    BUTTON_NOTIFY_EF82 = 'ef82'  # N
    UNKNOWN_EF83 = 'ef83'  # R

    BATTERY_LEVEL = '2a19'  # 0-63

    MODEL_NUMBER = '2a24'  # "SkaleII"

    FW_REVISION = '2a26'
    HW_REVISION = '2a27'
    SW_REVISION = '2a28'
    MANUFACTURER_NAME = '2a29'  # "ATOMAX INC."

    UNKNOWN = '0f050002-3225-44b1-b97d-d3274acb29de'  # R

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
