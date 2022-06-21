"""
Copyright © 2022 Mimoja. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import enum
import sys
import time
from typing import Callable

import pyDE1
from pyDE1.scale import Scale
from pyDE1.scale.events import ScaleWeightUpdate

logger = pyDE1.getLogger('Scale.FelicitaArc')

class FelicitaArc(Scale):

    def __init__(self):
        super(FelicitaArc, self).__init__()
        self._nominal_period = 0.1  # seconds per sample
        self._minimum_tare_request_interval = 2.5 * self._nominal_period # Guessed, not tested
        self._sensor_lag = 0.45  # seconds, including all transit delays
        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"

        # Enable tare on button 1, hold UUID if need to unsubscribe
        self._button_1_tare_subscriber_id = None
        self._supervisor_button = None

        # Linux, at least on an RPi 3B, needs response=True for write_gatt_char
        self._write_gatt_char_response = sys.platform == 'linux'

    async def standard_initialization(self, hold_notification=False):
        await super(FelicitaArc, self).standard_initialization(
            hold_notification=True)
        if not hold_notification:
            await self._notify_ready()

    async def update_self_from_device(self):
        # Not all HW revisions allow for information fetching
        raise NotImplementedError

    async def start_sending_weight_updates(self):
        await self._bleak_client.start_notify(
            Characteristic.MAIN.cuuid,
            self._create_weight_update_hander())
        logger.info("Sending weight updates")

    async def stop_sending_weight_updates(self):
        await self._bleak_client.stop_notify(
            Characteristic.MAIN.cuuid)
        logger.info("Stopped weight updates")

    def is_sending_weight_updates(self):
        return NotImplementedError

    async def _tare_internal(self):
        await self.send_command(Command.TARE)
        logger.info("Internal tare sent")

    async def current_weight(self):
        raise NotImplementedError

    async def display_on(self):
        raise NotImplementedError

    async def display_off(self):
        raise NotImplementedError

    async def set_grams(self):
        raise NotImplementedError


    @property
    def supports_button_press(self):
        return False

    async def start_sending_button_updates(self):
        raise NotImplementedError

    async def stop_sending_button_updates(self):
        raise NotImplementedError

    async def send_command(self, command: "Command"):
        await self._bleak_client.write_gatt_char(command.cuuid, command.value,
            response=self._write_gatt_char_response)

    def _create_weight_update_hander(self) -> Callable:
        scale = self

        async def weight_update_handler(sender, data):
            nonlocal scale

            if len(data) < 9:
                return

            now = time.time()

            header1 = data[0]
            header2 = data[1]
            
            sign = data[2]
            weight = int(data[3:]) / 100.0


            if chr(sign) == '-':
                weight *= -1
            

            self._update_scale_time_estimator(now)

            await scale.event_weight_update.publish(
                ScaleWeightUpdate(
                    arrival_time=now,
                    scale_time=self._scale_time_from_latest_arrival(now),
                    weight=weight
                ))

        return weight_update_handler


class Characteristic(enum.Enum):

    MAIN =    'FFE1'  # RWN
    @property
    def cuuid(self):
        return f"0000{self.value}-0000-1000-8000-00805f9b34fb"


# These typically get written to CONFIGURATION_EF80
class Command(enum.Enum):
    TARE = b'\x54'

    TIMER_ZERO = b'\x43'
    TIMER_START = b'\x52'
    TIMER_STOP = b'\x53'

    @property
    def cuuid(self):
        return Characteristic.CONFIGURATION_EF80.cuuid


Scale.register_constructor(FelicitaArc, 'FelicitaArc')