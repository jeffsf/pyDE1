"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import time

from copy import deepcopy
from typing import Union, Optional

from pyDE1.de1.ble import CUUID

from pyDE1.de1.c_api import PackedAttr, MMR0x80LowAddr, decode_one_mmr


class NotifyState ():

    def __init__(self, name: str):
        self.name = str(name)
        self.last_requested: Optional[float] = None
        self.last_updated: Optional[float] = None
        self._last_value: Optional[PackedAttr] = None
        self._ready_event: asyncio.Event = asyncio.Event()

    @property
    def last_value(self):
        # Paranoia, perhaps
        return deepcopy(self._last_value)

    @property
    def ready_event(self):
        return self._ready_event

    @property
    def update_complete(self):
        """
        last_updated is after last_requested
        :return: bool
        """
        return (self.last_requested is not None
                and self.last_updated is not None
                and self.last_updated > self.last_requested)

    def mark_requested(self, request_time=None):
        if request_time is None:
            request_time = time.time()
        self._ready_event.clear()
        self.last_requested = request_time

        return self._ready_event

    def mark_updated(self, obj: PackedAttr, update_time=None):
        if update_time is None:
            update_time = time.time()
        if self.last_requested is None:
            logger = logging.getLogger(f"{self.name}.Notify")
            logger.error(f"Update with no last_requested on {self.name}")
        self._last_value = obj
        self.last_updated = update_time
        self._ready_event.set()

        return self._ready_event


class NotificationState (NotifyState):

    def __init__(self, cuuid: CUUID):
        name = str(cuuid)
        super(NotificationState, self).__init__(name)
        self._cuuid = cuuid
        self._is_notifying = False

    @property
    def cuuid(self):
        return self._cuuid

    def mark_updated(self, obj: PackedAttr, update_time=None):
        super(NotificationState, self).mark_updated(obj, update_time)
        self._is_notifying = True

    @property
    def is_notifying(self):
        """
        There is a an acknowledged race condition here.
        It is possible for a stop_notifying to be requested
        and then a notification to be received.
        """
        return self._is_notifying

    def mark_ended(self):
        self._is_notifying = False



class MMR0x80Data (NotifyState):

    def __init__(self, addr_low: Union[MMR0x80LowAddr, int]):
        name = f"MMR0x80LowAddr.0x{addr_low:04x}"
        super(MMR0x80Data, self).__init__(name)
        self._addr_low = addr_low
        self._data_raw: Optional[Union[bytes, bytearray]] = None
        self._data_decoded: Optional[Union[bytes, bytearray,
                                           str, int, float, bool,
                                           dict]] = None

    @property
    def data_raw(self):
        return self._data_raw

    @data_raw.setter
    def data_raw(self, value):
        self._data_raw = value
        self._data_decoded = decode_one_mmr(0x80, self._addr_low, value)

    @property
    def data_decoded(self):
        return self._data_decoded


