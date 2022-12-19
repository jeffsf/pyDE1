"""
Copyright © 2022 Mimoja. All Rights Reserved.
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

Content by Mimoja used under grant of GPL-v3.0-only at
https://github.com/Mimoja/pyDE1/blob/stable/src/pyDE1/scale/felicita_arc.py

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import enum
import time

import pyDE1
from pyDE1.scale.events import ScaleWeightUpdate
from pyDE1.scale.generic_scale import register_scale_class, GenericScale


logger = pyDE1.getLogger('Scale.FelicitaArc')


@register_scale_class
class FelicitaArc (GenericScale):

    _supports_prefixes = ['FelicitaArc']

    def __init__(self):
        super(FelicitaArc, self).__init__()
        self._adopt_sync()

    def _adopt_sync(self):
        self._nominal_period = 0.1  # seconds per sample
        self._minimum_tare_request_interval = 2.5 * self._nominal_period
        self._sensor_lag = 0.45  # seconds, including all transit delays
        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"

    async def _adopt_class(self):
        self._adopt_sync()

    async def _leave_class(self):
        pass   # Nothing other than common attributes set

    async def start_sending_weight_updates(self):
        await self._bleak_client.start_notify(
            Characteristic.MAIN.cuuid,
            self._weight_update_hander)
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
        return None

    async def display_on(self):
        pass
        logger.info("Display on")

    async def display_off(self):
        pass
        logger.info("Display off")

    async def set_grams(self):
        pass
        logger.info("Grams selected")

    @property
    def supports_button_press(self):
        return False

    async def send_command(self, command: "Command"):
        await self._bleak_client.write_gatt_char(
            command.cuuid,
            command.value,
            response=self._write_gatt_char_response)

    async def _weight_update_handler(self, sender, data):

        try:
            now = time.time()
            if len(data) < 9:
                return

            # data[0:2] is a header
            sign = data[2]
            weight = int(data[3:]) / 100.0

            if chr(sign) == '-':
                weight *= -1

            self._update_scale_time_estimator(now)

            await self.event_weight_update.publish(
                ScaleWeightUpdate(
                    arrival_time=now,
                    scale_time=self._scale_time_from_latest_arrival(now),
                    weight=weight
                ))
        except Exception as e:
            logger.exception(e)
            raise e


class Characteristic(enum.Enum):

    MAIN =    'FFE1'  # RWN

    @property
    def cuuid(self):
        return f"0000ffe1-0000-1000-8000-00805f9b34fb"


class Command(enum.Enum):

    TARE = b'\x54'

    TIMER_ZERO = b'\x43'
    TIMER_START = b'\x52'
    TIMER_STOP = b'\x53'

    @property
    def cuuid(self):
        return Characteristic.MAIN.cuuid
