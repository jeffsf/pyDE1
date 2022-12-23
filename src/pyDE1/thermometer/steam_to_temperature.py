"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import time

from _operator import mul
from datetime import datetime
from typing import Optional, Union

import pyDE1
import pyDE1.shutdown_manager as sm

from pyDE1.config import config
from pyDE1.de1 import DE1
from pyDE1.de1.c_api import API_MachineStates
from pyDE1.de1.events import StateUpdate
from pyDE1.thermometer.bluedot import BlueDOT, BlueDOTUpdate
from pyDE1.utils import EventReadOnly


class SteamTempController:
    """
    Based on https://github.com/jeffsf/steam-to-temperature
    Rewritten for inclusion within pyDE1 directly

    This is not generalized to anything except the BlueDOT
    """

    def __init__(self, thermometer: BlueDOT):

        self.logger = pyDE1.getLogger('SteamTemp')

        self._thermometer = thermometer
        self._tat_estimator = TimeAtTargetEstimator()
        self._target: Optional[float] = None
        self._trigger_time = 0  # Cache between temperature updates

        self._de1 = DE1()

        self._on_trigger_event = asyncio.Event()
        self._on_trigger_event_ro = EventReadOnly(self._on_trigger_event)
        self._trigger_checker_task: Optional[asyncio.Task] = None

        loop = asyncio.get_running_loop()
        loop.create_task(
            self._thermometer.updates.subscribe(self._thermometer_subscriber))
        loop.create_task(
            self._de1.event_state_update.subscribe(self._de1_state_subscriber))

    @property
    def target(self):
        return self._tat_estimator.target

    @target.setter
    def target(self, value):
        self.logger.info(f"Target set: {value}")
        self._tat_estimator.target = value

    @property
    def has_triggered(self):
        return self._on_trigger_event.is_set()

    async def on_trigger_event(self):
        return self._on_trigger_event_ro

    # End of external API

    # The thermometer updates once per second, which isn't fast enough
    # to hit within one degree, especially for smaller volumes

    async def _trigger_checker(self):

        await asyncio.sleep(config.steam.SKIP_INITIAL_SECONDS)

        while (not self.has_triggered
               and self._de1.current_state == API_MachineStates.Steam
               and not sm.shutdown_underway.is_set()):
            now = time.time()
            if (self._trigger_time and
                    now >= self._trigger_time - config.steam.STOP_LAG):
                self._on_trigger_event.set()
                self.logger.info("Stopping steam with {} {} target".format(
                    self._target, self._thermometer.units.name))
                # TODO: Is this call up-to-date with firmware changes
                await self._de1.end_steam()
            else:
                # At 250 cal/sec, 100 g is 2.5°C / sec
                # 0.1 seconds should be well within 1°C
                await asyncio.sleep(0.1)
        if not self._on_trigger_event.set():
            self.logger.warning(
                "Trigger exited early for target {}, {},{}".format(
                    self._target,
                    self._de1.current_state, self._de1.current_substate
                ))
        self._trigger_checker_task = None
        await self.control_deactivate()

    async def control_activate(self):
        if not self._thermometer.is_ready:
            self.logger.error(
                f"{self._thermometer} is not ready, continuing anyway")
        if self._thermometer.is_ready:
            asyncio.create_task(self._thermometer.sample_fast())
        try:
            self._trigger_checker_task.cancel()
            self.logger.warning(
                "control_activate() called when active, reinitializing")
        except (AttributeError, asyncio.CancelledError):
            pass
        self._trigger_checker_task = None
        self._trigger_time = None
        self._on_trigger_event.clear()
        await self._tat_estimator.reset()
        self._trigger_checker_task = asyncio.create_task(
            self._trigger_checker(), name='TriggerChecker')
        self.logger.info("Control activated")

    async def control_deactivate(self):
        self.logger.info("No longer being controlled")
        self._trigger_time = None
        self._on_trigger_event.clear()
        await self._tat_estimator.reset()
        try:
            self._trigger_checker_task.cancel()
        except (AttributeError, asyncio.CancelledError):
            pass
        self._trigger_checker_task = None
        if self._thermometer.is_ready:
            await self._thermometer.sample_normal()

    async def _thermometer_subscriber(self, update: BlueDOTUpdate):

        # Use the BlueDOT high-alarm as the steam-to target

        self._target = update.high_alarm

        if self._trigger_checker_task is not None:
            self._trigger_time = await self._tat_estimator.new_sample(
                sample_time=update.arrival_time,
                temperature=update.temperature
            )
            if self._trigger_time:
                self.logger.info(
                    "TAT: {} in {:.3f} sec, {:.1f} °/s "
                    "at {:.1f} est {:.1f} rpt".format(
                        datetime.fromtimestamp(
                            self._trigger_time).time().isoformat(
                            timespec='milliseconds'),
                        self._trigger_time - time.time(),
                        self._tat_estimator.rate_of_rise,
                        self._tat_estimator.current_est,
                        update.temperature
                    )
                )

    async def _de1_state_subscriber(self, update: StateUpdate):
        if self._thermometer.address in ('', None):
            return

        if update.state == API_MachineStates.Sleep:
            if not self._thermometer.is_released:
                self.logger.info("DE1 reported Sleep, releasing thermometer")
                if self._thermometer.is_ready:
                    await self._thermometer.sample_slow()
                await self._thermometer.request_release()
        else:
            if not self._thermometer.is_ready:
                self.logger.info(
                    f"DE1 reported {update.state.name},{update.substate.name}, "
                    "capturing thermometer")
                await self._thermometer.request_capture()


class TimeAtTargetEstimator:
    """
    Class that encapsulates being able to estimate
    when the rate of rise will reach the target
    """

    logger = pyDE1.getLogger('SteamTemp.TAT')

    def __init__(self):
        self._history_time = []
        self._history_temperature = []
        self._history_lock = asyncio.Lock()
        self.big_gap = 2.1  # seconds, if gap exceeds, reset estimator
        self.target = None
        self._bhat = None
        self._mhat = None

    async def reset(self):
        async with self._history_lock:
            self._reset_have_lock()

    async def new_sample(self, sample_time: float,
                         temperature: Union[int, float]) -> Optional[float]:
        """
        Call when a new sample arrives

        Returns the time at target estimate as absolute time.time() reference
        """
        async with self._history_lock:
            if self._history_available:
                if (dt := sample_time - self._history_time[-1]) > self.big_gap:
                    self.logger.warning(
                        f"Resetting history after {dt:.1f} sec gap")
                    self._reset_have_lock()
            self._history_time.append(sample_time)
            while (len(self._history_time)
                    > config.steam.MAX_SAMPLES_FOR_ESTIMATE):
                self._history_time.pop(0)
            self._history_temperature.append(temperature)
            while (len(self._history_temperature)
                    > config.steam.MAX_SAMPLES_FOR_ESTIMATE):
                self._history_temperature.pop(0)

            return self._estimate_time_at_target_have_lock()

    async def estimate_time_at_target(self) -> Optional[float]:
        """
        Returns the time at target estimate as reference
        on same timescale as samples are reported
        """
        async with self._history_lock:
            return self._estimate_time_at_target_have_lock()

    @property
    def rate_of_rise(self):
        return self._mhat

    @property
    def current_est(self):
        return self._bhat

    def _reset_have_lock(self):
        self._history_time = []
        self._history_temperature = []
        self._mhat = None
        self._bhat = None
        self.logger.info("Reset history")

    @property
    def _history_available(self):
        # Ultra safe
        return min(len(self._history_temperature), len(self._history_time))

    def _estimate_time_at_target_have_lock(self) -> Optional[float]:
        # Use a least-squares estimator
        ns = self._history_available
        if ns < 2:
            t_target = None
        else:
            # Keep time scaled reasonably
            t0 = self._history_time[-1]
            t_norm = [t - t0 for t in self._history_time[-ns:]]
            s_x = sum(t_norm)
            s_y = sum(self._history_temperature[-ns:])
            s_xx = sum([x * x for x in t_norm])
            # s_yy = sum([y * y for y in self._history_temperature[-ns:]])
            s_xy = sum(map(mul,
                           t_norm,
                           self._history_temperature[-ns:]))
            self._mhat = (ns * s_xy - (s_x * s_y)) \
                   / (ns * s_xx - (s_x * s_x))
            if self._mhat:
                self._bhat = (s_y / ns) - self._mhat * (s_x / ns)
                t_target = t0 + (self.target - self._bhat) / self._mhat
            else:
                self._bhat = None
                t_target = None

        return t_target
