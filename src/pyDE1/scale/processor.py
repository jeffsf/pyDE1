"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

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
from pyDE1.event_manager import SubscribedEvent
from pyDE1.event_manager.events import ConnectivityState
from pyDE1.exceptions import DE1NoAddressError, DE1APIValueError
from pyDE1.scale import Scale, scale_factory, recognized_scale_prefixes
from pyDE1.scale.events import (
    ScaleWeightUpdate, ScaleTareSeen, WeightAndFlowUpdate
)
from pyDE1.scanner import (
    BleakScannerWrapped, DiscoveredDevices, find_first_matching
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

        self._scale: Optional[Scale] = None
        self._scale_weight_update_id: Optional[UUID] = None
        self._scale_tare_seen_id: Optional[UUID] = None
        self._state_update_id: Optional[UUID] = None
        self._history_max = 10  # Will be extended if needed by Estimator
        self._history_time: List[float] = []
        self._history_weight: List[float] = []
        self._history_lock = asyncio.Lock()
        # set_scale needs _history_lock
        self._scale = None
        self._event_weight_and_flow_update = SubscribedEvent(self)

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

        # This is a bit tricky, as self._scale is None
        bare_scale = Scale()
        asyncio.create_task(
            bare_scale._event_connectivity.publish(
                bare_scale._connectivity_change(
                    arrival_time=time.time(),
                    state=ConnectivityState.DISCONNECTED))
        )

    @property
    def scale(self):
        return self._scale

    async def set_scale(self, scale: Optional[Scale]):
        # NB: A Scale is self-referential and may not be GCed if "dropped" here
        if self._scale == scale:
            return
        # Unsubscribe the existing scale
        if self._scale is not None:
            await asyncio.gather(
                self._scale.event_weight_update.unsubscribe(
                    self._scale_weight_update_id
                ),
                self._scale.event_tare_seen.unsubscribe(
                    self._scale_tare_seen_id
                ),
                DE1().event_state_update.unsubscribe(
                    self._state_update_id
                )
            )

        # Always set
        self._scale = scale

        if self._scale is not None:
            (
                self._scale_weight_update_id,
                self._scale_tare_seen_id,
                self._state_update_id,

            ) = await asyncio.gather(
                self._scale.event_weight_update.subscribe(
                    self._create_scale_weight_update_subscriber()),

                self._scale.event_tare_seen.subscribe(
                    self._create_scale_tare_seen_subscriber()),

                DE1().event_state_update.subscribe(
                    self._create_state_update_subscriber()),

                return_exceptions=True
            )
        await self._reset()  # New scale, toss old history

        return self

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
    def scale_type(self):
        if self.scale is not None:
            return self.scale.type
        else:
            return None

    @property
    def scale_connectivity(self):
        if self.scale is not None:
            return self.scale.connectivity
        else:
            return ConnectivityEnum.NOT_CONNECTED

    #
    # Self-contained call for API
    #

    async def first_if_found(self, doit: bool):
        if self.scale and self.scale.is_connected:
            logger.warning(
                "first_if_found requested, but already connected. "
                "No action taken.")
        elif not doit:
            logger.warning(
                "first_if_found requested, but not True. No action taken.")
        else:
            device = await find_first_matching(
                recognized_scale_prefixes())
            if device:
                await self.change_scale_to_id(device.address)
        return self.scale_address

    async def change_scale_to_id(self, ble_device_id: Optional[str]):
        """
        For now, this won't return until connected or fails to connect
        As a result, will trigger the timeout on API calls
        """
        logger.info(f"Request to replace scale with {ble_device_id}")

        # TODO: Need to make distasteful assumption that the id is the address
        try:
            if self.scale_address == ble_device_id:
                logger.info(f"Already using {ble_device_id}. No action taken")
                return
        except AttributeError:
            pass

        old_scale = self.scale

        try:
            if ble_device_id is None:
                # Straightforward request to disconnect and not replace
                await self.set_scale(None)

            else:
                ble_device = DiscoveredDevices().ble_device_from_id(ble_device_id)
                if ble_device is None:
                    logger.warning(f"No record of {ble_device_id}, initiating scan")
                    # TODO: find_device_by_filter doesn't add to DiscoveredDevices
                    ble_device = await BleakScannerWrapped.find_device_by_address(
                        ble_device_id,
                        timeout=config.bluetooth.CONNECT_TIMEOUT)
                if ble_device is None:
                    raise DE1NoAddressError(
                        f"Unable to find device with id: '{ble_device_id}'")

                try:
                    logger.info(f"Disconnecting {self.scale}")
                    await self.scale.disconnect()
                except AttributeError:
                    pass

                new_scale = scale_factory(ble_device)
                if new_scale is None:
                    raise DE1APIValueError(
                        f"No scale could be created from {ble_device}")

                await self.set_scale(new_scale)
                await self.scale.connect()

        finally:
            # Scale is self-referential, make sure GC-ed
            if old_scale is not None and self.scale != old_scale:
                await old_scale.disconnect()
                old_scale.decommission()
                del old_scale

    async def connectivity_setter(self, value):
        assert isinstance(value, ConnectivityEnum), \
            f"mode of {value} not a ConnectivityEnum"
        if value is ConnectivityEnum.NOT_CONNECTED:
            if self.scale is not None:
                await self.scale.disconnect()
        elif value is ConnectivityEnum.CONNECTED:
            if self.scale is not None:
                await self.scale.connect()
        else:
            raise DE1APIValueError(
                "Only CONNECTED and NOT_CONNECTED can be set, "
                f"not {value}")

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

    def _create_scale_tare_seen_subscriber(self) -> Callable:
        scale_processor = self

        async def scale_tare_seen_subscriber(sts: ScaleTareSeen):
            nonlocal scale_processor
            await scale_processor._reset()

        return scale_tare_seen_subscriber

    def _create_scale_weight_update_subscriber(self) -> Callable:
        scale_processor = self

        async def scale_weight_update_subscriber(swu: ScaleWeightUpdate):
            nonlocal scale_processor
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
                               - scale_processor._history_time[-1]) > TOO_LONG):
                        logger.warning(
                            "Resetting scale due to gap in reports: "
                            f"{dt:0.3f} > {TOO_LONG} s")
                        scale_processor._reset_have_lock()
                        return
                except IndexError:
                    pass  # (No elements in the history list)
                scale_processor._history_time.append(swu.scale_time)
                scale_processor._history_weight.append(swu.weight)
                # Unlikely, but possibly the case that history_max shrunk
                while len(scale_processor._history_time) \
                        > scale_processor._history_max:
                    scale_processor._history_time.pop(0)
                while len(scale_processor._history_weight) \
                        > scale_processor._history_max:
                    scale_processor._history_weight.pop(0)

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

        return scale_weight_update_subscriber

    def _create_state_update_subscriber(self) -> Callable:
        scale_processor = self

        async def state_update_subscriber(su: StateUpdate):
            nonlocal scale_processor
            scale = scale_processor.scale
            if (su.previous_state == API_MachineStates.Sleep
                    and su.state != API_MachineStates.Sleep
                    and scale.address is not None
                    and not scale.is_connected):
                logger.info(
                    "Reconnecting to scale as DE1 left Sleep to "
                    f"{API_MachineStates(su.state).name}")
                scale._reset_reconnect()
                await scale_processor.scale._reconnect()

        return state_update_subscriber


# Prevent dreaded "circular import" problems
from pyDE1.scale.estimator import CurrentWeight, AverageFlow, \
    MedianWeight, MedianFlow
