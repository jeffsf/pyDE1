"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum
import logging


from typing import Optional, List, Tuple, Coroutine, Callable
from uuid import UUID

import pyDE1.default_logger
from pyDE1.scale import Scale, ScaleError
from pyDE1.event_manager import SubscribedEvent
from pyDE1.scale.events import ScaleWeightUpdate, ScaleTareSeen, \
    WeightAndFlowUpdate


class ScaleProcessorError (ScaleError):
    def __init__(self):
        super(ScaleProcessorError, self).__init__()


class ScaleProcessor:
    """
    Subscribes to weight-update events from a scale
    Provides estimates of weight and mass-flow via
    WeightAndFlowUpdate events

    Should be able to init and "wire to" without a scale
    Scales should be able to be changed on the fly
    """

    def __init__(self, scale: Optional[Scale]=None):

        self._scale: Optional[Scale] = None
        self._scale_weight_update_id: Optional[UUID] = None
        self._scale_tare_seen_id: Optional[UUID] = None
        self._history_max = 10  # Will be extended if needed by Estimator
        self._history_time: List[float] = []
        self._history_weight: List[float] = []
        self._history_lock = asyncio.Lock()
        # set_scale needs _history_lock
        asyncio.create_task(self.set_scale(scale))
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
            AverageFlow(self, '_average_flow', 10),
            MedianWeight(self, '_median_weight', 10),
            MedianFlow(self, '_median_flow', 10, 5),
        ]

    @property
    def scale(self):
        return self._scale

    async def set_scale(self, scale: Scale):
        # This feels like it shoud be await-ed
        # drop subscription to any previous scale
        if self._scale == scale:
            return
        if self._scale is not None:
            await asyncio.gather(
                self._scale.event_weight_update.unsubscribe(
                    self._scale_weight_update_id
                ),
                self._scale.event_tare_seen.unsubscribe(
                    self._scale_tare_seen_id
                )
            )
        self._scale = scale
        # Can't assign in an await easily and no "async lambda"
        # TODO: Replace this with (a, b) = await asyncio.gather(ta, tb)
        self._scale_weight_update_id = \
            await self._scale.event_weight_update.subscribe(
                self._create_scale_weight_update_subscriber()
            )
        self._scale_tare_seen_id = \
            await self._scale.event_tare_seen.subscribe(
                self._create_scale_tare_seen_subscriber()
            )
        await self._reset()  # New scale, toss old history

        return self

    @property
    def event_weight_and_flow_update(self):
        return self._event_weight_and_flow_update

    async def _reset(self):
        async with self._history_lock:
            self._history_time = []
            self._history_weight = []
            # probably should clear any pending updates
            # as they may be pre-tare

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

# Prevent dreaded "circular import" problems
from pyDE1.scale.estimator import CurrentWeight, AverageFlow, \
    MedianWeight, MedianFlow
