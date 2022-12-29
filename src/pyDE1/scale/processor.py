"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import time
from typing import Optional, List, Callable
from uuid import UUID

import pyDE1
from pyDE1.config import config
from pyDE1.de1 import DE1
from pyDE1.de1.c_api import API_MachineStates
from pyDE1.de1.events import StateUpdate
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager.event_manager import SubscribedEvent
from pyDE1.event_manager.events import (
    DeviceAvailabilityState, DeviceRole,
)
from pyDE1.exceptions import DE1NoAddressError, DE1APIValueError
from pyDE1.scale.generic_scale import GenericScale

from pyDE1.scale.events import (
    ScaleWeightUpdate, ScaleTareSeen, WeightAndFlowUpdate
)
from pyDE1.scanner import (
    find_first_matching,
    RegisteredPrefixes,
)
from pyDE1.singleton import Singleton

logger = pyDE1.getLogger('Scale.Processor')


class ScaleProcessor (Singleton):
    """
    Subscribes to weight-update events from a scale
    Provides estimates of weight and mass-flow via
    WeightAndFlowUpdate events

    Should be able to init and "wire to" without a scale
    Scales should be able to be changed on the fly
    """

    # NB: This is intentionally done in _singleton_init() and not __init__()
    #     See Singleton and Guido's notes there
    #
    # def __init__(self):
    #     pass

    def _singleton_init(self):

        self._scale = GenericScale()
        self._scale_weight_update_id: Optional[UUID] = None
        self._scale_tare_seen_id: Optional[UUID] = None
        self._scale_changed_id: Optional[UUID] = None
        self._state_update_id: Optional[UUID] = None
        self._history_max = 10  # Will be extended if needed by Estimator
        self._history_time: List[float] = []
        self._history_weight: List[float] = []
        self._history_lock = asyncio.Lock()
        # set_scale needs _history_lock
        self._event_weight_and_flow_update = SubscribedEvent(self)

        self.CURRENT_WEIGHT_MAX_AGE = 1.0  # seconds, else return None

        # init of Estimator checks that the targets are present
        # (good practice to explicily declare anyways)
        self._current_weight: float = 0
        self._current_weight_time: float = 0
        self._average_flow: float = 0
        self._average_flow_time: float = 0
        self._median_weight: float = 0
        self._median_weight_time: float = 0
        self._median_flow: float = 0
        self._median_flow_time: float = 0
        self._estimators = [
            CurrentWeight(self, '_current_weight'),
            AverageFlow(self, '_average_flow', 11),
            MedianWeight(self, '_median_weight', 11),
            MedianFlow(self, '_median_flow', 11, 5),
        ]

        asyncio.get_running_loop().create_task(self.wire_scale())

    @property
    def scale(self):
        return self._scale

    async def wire_scale(self):
        (
            self._scale_weight_update_id,
            self._scale_tare_seen_id,
            self._scale_changed_id,
            self._state_update_id,

        ) = await asyncio.gather(
            self._scale.event_weight_update.subscribe(
                self._weight_update_subscriber),

            self._scale.event_tare_seen.subscribe(
                self._tare_seen_subscriber),

            self._scale.event_scale_changed.subscribe(
                self._reset()
            ),

            DE1().event_state_update.subscribe(
                self._state_update_subscriber),

            return_exceptions=True
        )
        await self._reset()  # New scale, toss old history

    # Provide "null-safe" methods for API

    @property
    def scale_address(self):
        if self.scale is not None:
            return self.scale.address
        else:
            return None

    @property
    def scale_name(self):
        if self.scale is not None:
            return self.scale.name
        else:
            return None

    @property
    def scale_connectivity(self):
        if self.scale is not None:
            return self.scale.connectivity
        else:
            return ConnectivityEnum.NOT_CONNECTED

    async def connectivity_setter(self, value):
        if self.scale is not None:
            return await self.scale.connectivity_setter(value)
        else:
            raise DE1NoAddressError("No scale associated")

    @property
    def scale_availability_state(self):
        if self.scale is not None:
            return self.scale.availability_state
        else:
            return DeviceAvailabilityState.UNKNOWN

    async def scale_availability_setter(self, value):
        if self.scale is not None:
            return await self.scale.availability_setter(value)
        else:
            raise DE1NoAddressError("No scale associated")

    @property
    def device_availability_last_sent(self):
        return self.scale.device_availability_last_sent

    @property
    def current_weight(self) -> Optional[float]:
        if (time.time() - self._current_weight_time
                < self.CURRENT_WEIGHT_MAX_AGE):
            return self._current_weight
        else:
            return None



    #
    # Self-contained call for API
    #

    async def connect_to_first_if_found(self):
        if self.scale.is_connected:
            logger.warning(
                "'scan' requested, but already connected. "
                "No action taken.")
        else:
            device = await find_first_matching(DeviceRole.SCALE)
            if device:
                await self.scale.change_address(device)
                await self.scale.capture()
        return self.scale_address


    async def change_scale_to_id(self, ble_device_id: Optional[str]):
        """
        For now, this won't return until connected or fails to connect
        As a result, will trigger the timeout on API calls
        """
        logger.info(f"Request to replace scale with {ble_device_id}")

        if ble_device_id == 'scan':
            await self.connect_to_first_if_found()
        else:
            await self.scale.change_address(ble_device_id)

        return self.scale.address

    @property
    def event_weight_and_flow_update(self):
        return self._event_weight_and_flow_update

    async def _reset(self):
        async with self._history_lock:
            self._reset_have_lock()

    def _reset_have_lock(self):
        self._history_time = []
        self._history_weight = []
        # TODO: Perhaps should clear any pending updates
        #       as they may be pre-tare

    @property
    def _history_available(self):
        # Ultra safe
        return min(len(self._history_weight), len(self._history_time))

    async def _tare_seen_subscriber(self, sts: ScaleTareSeen):
        await self._reset()

    async def _weight_update_subscriber(self, swu: ScaleWeightUpdate):
        # TODO: This has the potential to get really messy
        #       Make sure this doesn't block other things
        # The Skale can return multiple updates in milliseconds
        # Is there any guarantee that they will be processed in order?
        # "Acquiring a lock is fair: the coroutine that proceeds
        #  will be the first coroutine that started waiting on the lock."
        async with self._history_lock:
            # Detect a gap in reporting being "too long"
            # (typically from a disconnect/reconnect)
            # A skip of three at 150 ms per update with the Skale II
            TOO_LONG = 0.8 # seconds
            try:
                if ((dt := swu.scale_time
                           - self._history_time[-1]) > TOO_LONG):
                    logger.warning(
                        "Resetting scale due to gap in reports: "
                        f"{dt:0.3f} > {TOO_LONG} s")
                    self._reset_have_lock()
                    return
            except IndexError:
                pass  # (No elements in the history list)
            self._history_time.append(swu.scale_time)
            self._history_weight.append(swu.weight)
            # Unlikely, but possibly the case that history_max shrunk
            while len(self._history_time) \
                    > self._history_max:
                self._history_time.pop(0)
            while len(self._history_weight) \
                    > self._history_max:
                self._history_weight.pop(0)

            # There's nothing here really parallelizable
            for estimator in self._estimators:
                estimator.estimate()

            await self._event_weight_and_flow_update.publish(
                WeightAndFlowUpdate(
                    arrival_time=swu.arrival_time,
                    scale_time=swu.scale_time,
                    current_weight=self._current_weight,
                    current_weight_time=self._current_weight_time,
                    average_flow=self._average_flow,
                    average_flow_time=self._average_flow_time,
                    median_weight=self._median_weight,
                    median_weight_time=self._median_weight_time,
                    median_flow=self._median_flow,
                    median_flow_time=self._median_flow_time,
                )
            )

    async def _state_update_subscriber(self, su: StateUpdate):
        scale = self.scale
        if (su.previous_state == API_MachineStates.Sleep
                and su.state != API_MachineStates.Sleep
                and scale.address not in ('', None)
                and not scale.is_captured):
            logger.info(
                "Reconnecting to scale as DE1 left Sleep to "
                f"{API_MachineStates(su.state).name}")
            await self.scale.request_capture()
        # If DE1 reports Sleep while the scale is awaiting connection
        # such as in change_scale_to_id(), a timeout will occur.
        # This happens when clicking both "Scan" buttons.
        elif (su.state == API_MachineStates.Sleep
              and scale.is_captured):
            logger.info(
                "Releasing scale as DE1 entered Sleep,"
                f"{API_MachineStates(su.substate).name}")
            await self.scale.request_release()

# Prevent dreaded "circular import" problems
from pyDE1.scale.estimator import CurrentWeight, AverageFlow, \
    MedianWeight, MedianFlow
