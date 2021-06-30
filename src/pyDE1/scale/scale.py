"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import time

from typing import Optional, Callable, Coroutine, Union

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from pyDE1.bleak_client_wrapper import BleakClientWrapped
from pyDE1.exceptions import DE1APIValueError
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager import SubscribedEvent
from pyDE1.event_manager.events import ConnectivityState, ConnectivityChange
from pyDE1.scale.events import ScaleWeightUpdate, ScaleTareSeen

logger = logging.getLogger('Scale')


class ScaleError(RuntimeError):
    def __init__(self, *args, **kwargs):
        super(ScaleError, self).__init__(args, kwargs)


class ScaleNoAddressError(ScaleError):
    def __init__(self, *args, **kwargs):
        super(ScaleNoAddressError, self).__init__(args, kwargs)


class ScaleNotConnectedError(ScaleError):
    def __init__(self, *args, **kwargs):
        super(ScaleNotConnectedError, self).__init__(args, kwargs)


class Scale:

    def __init__(self):
        self._address = None
        self._name: Optional[str] = None

        # These are often model-specific, override in subclass init
        self._nominal_period = 0.1  # seconds per sample
        self._minimum_tare_request_interval = 2.5 * self._nominal_period
        self._sensor_lag = 0.38  # seconds, including all delays to arrival
        # From https://www.youtube.com/watch?v=SIzFhnZ32Y0
        # (James Hoffmann) at 4:51
        #   Hiroia    0.20
        #   Skale     0.33
        #   Felicita  0.45
        #   Acaia     0.64
        self._tare_timeout = 1.0  # seconds until considered coincidence
        self._tare_threshold = 0.05  # grams, within this, considered "at zero"
        self.hold_at_tare = False

        self._bleak_client: Optional[BleakClientWrapped] = None

        self._event_connectivity: SubscribedEvent = SubscribedEvent(self)
        self._event_weight_update: SubscribedEvent = SubscribedEvent(self)
        self._event_button_press: SubscribedEvent = SubscribedEvent(self)
        self._event_tare_seen: SubscribedEvent = SubscribedEvent(self)
        self._estimated_period = self._nominal_period
        self._last_weight_update_received = 0
        self._last_tare_request_sent = 0

        # TODO: Think about how to manage "tare seen"
        #       Could use asyncio.Event(), but what are the states
        #       and how do you "release" if it never arrives?
        #       It seems like the use case would be:
        #           request tare
        #           wait for tare
        #           if seen:
        #               continue
        #           else:
        #               do something else
        self._tare_requested = False
        self._period_estimator = self.PeriodEstimator(self._nominal_period)

        # Don't need to await this on instantiation
        asyncio.get_event_loop().create_task(
            self._event_weight_update.subscribe(self._create_self_callback()))

    @classmethod
    def device_adv_is_recognized_by(cls, device: BLEDevice, adv: AdvertisementData):
        """
        Think about how to have this scan the subclasses
        for the most-specific match.

        Also think about how to manage the possibility of a collection
        of scales, that might already be instantiated
        """
        raise NotImplementedError

    @property
    def type(self):
        return self.__class__.__name__

    @property
    def address(self):
        addr = self._address
        if isinstance(addr, BLEDevice):
            addr = addr.address
        return addr

    @address.setter
    def address(self, address: Union[BLEDevice, str]):
        if self.address is not None:
            raise DE1APIValueError(
                "Changing the scale address is not yet supported")
        # If using BLEDevice directly
        # AttributeError: 'BleakClientBlueZDBus' object has no attribute 'lower'
        try:
            address = address.address
        except AttributeError:
            pass
        self._address = address

    @property
    def name(self):
        return self._name

    @property
    def sensor_lag(self):
        return self._sensor_lag

    async def connect(self, timeout=5.0):

        class_name = type(self).__name__
        logger.info(f"Connecting to {class_name} at {self.address}")

        if self._bleak_client is None:
            if self.address is None:
                raise ScaleNoAddressError
            self._bleak_client = BleakClientWrapped(self.address)
        self._bleak_client.set_disconnected_callback(
            self._create_disconnect_callback()
        )

        await asyncio.gather(self._event_connectivity.publish(
            ConnectivityChange(arrival_time=time.time(),
                               state=ConnectivityState.CONNECTING)),
            self._bleak_client.connect(timeout=timeout),
        )

        if self.is_connected:
            self._address = self._bleak_client.address
            if self.name is None:
                self._name = self._bleak_client.name
            logger.info(f"Connected to {class_name} at {self.address}")
            await self._event_connectivity.publish(
                ConnectivityChange(arrival_time=time.time(),
                                   state=ConnectivityState.CONNECTED))
            # This can take some time, potentially delaying DE1 connection
            # At least BlueZ doesn't like concurrent connection requests
            asyncio.create_task(self.standard_initialization())

            # TODO: Does the ScaleProcessor get properly reset?

        else:
            logger.error(
                f"Connection failed to {class_name} at {self.address}")
            await self._event_connectivity.publish(
                ConnectivityChange(arrival_time=time.time(),
                                   state=ConnectivityState.DISCONNECTED))

    async def standard_initialization(self, hold_notification=False):
        """
        :param hold_notification: Since subclass may need to do more
        """
        logger.info("Scale.standard_initialization()")
        await self.display_on()
        await self.start_sending_weight_updates()
        if self.supports_button_press:
            await self.start_sending_button_updates()
        if not hold_notification:
            await self._notify_ready()

    async def _notify_ready(self):
        await self._event_connectivity.publish(
            ConnectivityChange(arrival_time=time.time(),
                               state=ConnectivityState.READY))
        logger.info("Ready")

    async def _notify_not_ready(self):
        await self._event_connectivity.publish(
            ConnectivityChange(arrival_time=time.time(),
                               state=ConnectivityState.NOT_READY))

    async def disconnect(self):
        class_name = type(self).__name__
        logger.info(f"Disconnecting from {class_name}")
        if self._bleak_client is None:
            logger.info(f"Disconnecting from {class_name}, no client")
            return
        await asyncio.gather(
            self._bleak_client.disconnect(),
            self._event_connectivity.publish(
                ConnectivityChange(arrival_time=time.time(),
                                   state=ConnectivityState.DISCONNECTING))
        )
        if self.is_connected:
            logger.error(
                f"Disconnect failed from {class_name} at {self.address}")
            await self._event_connectivity.publish(
                ConnectivityChange(arrival_time=time.time(),
                                   state=ConnectivityState.CONNECTED))
        else:
            logger.info(f"Scale.disconnect(): Disconnected from {class_name} at {self.address}")
            await self._event_connectivity.publish(
                ConnectivityChange(arrival_time=time.time(),
                                   state=ConnectivityState.DISCONNECTED))

    # TODO: Decide how to handle  self._disconnected_callback

    @property
    def is_connected(self):
        if self._bleak_client is None:
            return False
        else:
            return self._bleak_client.is_connected

    async def start_sending_weight_updates(self):
        raise NotImplementedError

    async def stop_sending_weight_updates(self):
        raise NotImplementedError

    @property
    def is_sending_weight_updates(self):
        raise NotImplementedError

    @property
    def supports_button_press(self):
        return False

    async def start_sending_button_updates(self):
        raise NotImplementedError

    async def stop_sending_button_updates(self):
        raise NotImplementedError

    async def tare(self):
        """
        A tare request can only be made every
        self._minimum_tare_request_interval seconds

        It doesn't make sense to hammer it as it will take
        at least one reporting period to "see" the tare
        """
        dt = time.time() - self._last_tare_request_sent
        if dt > self._minimum_tare_request_interval:
            await self._tare_internal()
            self._last_tare_request_sent = time.time()
            self._tare_requested = True
            logger.info(f"Tare request sent")
        else:
            logger.info(
                f"Tare request skipped, too soon, {dt:0.3f} seconds")
        return self._last_tare_request_sent


    async def _tare_internal(self):
        raise NotImplementedError

    async def current_weight(self):
        raise NotImplementedError

    async def display_on(self):
        raise NotImplementedError

    async def display_off(self):
        raise NotImplementedError

    # The two *_bool for API

    async def tare_with_bool(self, do_it=True):
        if do_it:
            await self.tare()

    async def display_bool(self, on):
        if on:
            await self.display_on()
        else:
            await self.display_off()

    @property
    def estimated_period(self):
        return self._estimated_period

    @property
    def event_weight_update(self):
        return self._event_weight_update

    @property
    def event_button_press(self):
        return self._event_button_press

    @property
    def event_tare_seen(self):
        return self._event_tare_seen

    def _scale_time_from_latest_arrival(self,
                                        latest_arrival: float):
        """
        Given the latest arrival, provide "best" estimate
        of when that weight was on the scale

        At present, just compensates for scale._scale_delay
        which should include transit delays and the like
        """
        return latest_arrival - self._sensor_lag

    def _update_scale_time_estimator(self,
                                     latest_arrival:float):
        """
        Call once per arrival to update any "fancy" algorithms such as PLL
        """
        pass

    def _create_self_callback(self) -> Coroutine:
        scale = self

        async def self_callback(swu: ScaleWeightUpdate) -> None:
            nonlocal scale
            dt = swu.arrival_time - scale._last_weight_update_received
            scale._last_weight_update_received = swu.arrival_time

            # TODO: Run profiler and evaluate if creating a task
            #       is consuming too much time

            asyncio.create_task(
                scale._period_estimator.process_arrival(dt))

            if scale._tare_requested:
                dt = swu.arrival_time - scale._last_tare_request_sent
                if dt > scale._tare_timeout:
                    scale._tare_requested = False
                    logger.error(f"No tare seen after {dt:0.03f} seconds")
                elif abs(swu.weight) < scale._tare_threshold:
                    scale._tare_requested = False
                    await scale.event_tare_seen.publish(
                        ScaleTareSeen(swu.arrival_time)
                    )
                    logger.info(f"Tare seen after {dt:0.03f} seconds")

            if scale.hold_at_tare:
                if abs(swu.weight) > scale._tare_threshold:
                    # Timing will be checked in scale.tare()
                    await scale.tare()

        return self_callback

    # TODO: Decide how to handle  self._disconnected_callback
    #   disconnected_callback (callable): Callback that will be scheduled in the
    #   event loop when the client is disconnected. The callable must take one
    #   argument, which will be this client object.

    # The callback seems to be expected to be a "plain" function
    # RuntimeWarning: coroutine 'DE1._create_disconnect_callback.<locals>.disconnect_callback'
    #                 was never awaited

    def _create_disconnect_callback(self) -> Callable:
        scale = self

        def disconnect_callback(client: BleakClientWrapped):
            nonlocal scale
            class_name = type(self).__name__
            logger.info(
                "disconnect_callback: "
                f"Disconnected from {class_name} at {client.address}, "
                "willful_disconnect: "
                f"{client.willful_disconnect}")
            asyncio.create_task(scale._event_connectivity.publish(
                ConnectivityChange(arrival_time=time.time(),
                                   state=ConnectivityState.DISCONNECTED)))

        return disconnect_callback

    @property
    def nominal_period(self):
        return self._nominal_period

    @nominal_period.setter
    def nominal_period(self, value):
        self._nominal_period = value
        self._period_estimator.reset(self._nominal_period)

    # Inner class
    class PeriodEstimator:
        """
        Estimate inter-arrival period from stream of arrivals

        Presently just an exponential moving average

        Skale II usually "bulks up" two or more reports on a 150-ms clock
        300 ms burbles aren't uncommon. A "normal" 50-ms stretch before its
        other half arrives would generate a (50/100) * k change.
        The other half then would generate (-100/100) * k change
        So k on the order of 1/1000 should be reasonable (10 sec, ~1 min settle)
        k of 1/10000 would be even better (100 sec, 10 min settle)
        Another way to look at this is 600 ms error / 600 s measurement ~ 0.1%

        Hand-in-hand with this is how long to consider a gap vs. a burble
        Nearly 5% of 150-ms windows from a SkaleII had 3 reports.
        Up to 6 in a window were observed. It dropped to 0.1% at 4 reports
        per window. Ignoring too many of these can lead to the estimate being off.
        Based on this, 300 ms (two periods) seems too short.
        300 + 150/2 = 375 ms is probably OK.
        450 + 150/2 = 525 ms is probablu conservative
        Try 500 ms to be reasonable.
        """

        def __init__(self, nominal_period: float):

            # TODO: How to update this for subclass changes?

            self._k = 1/10000
            self._ma = nominal_period
            self._too_long = 0.5  # seconds before considered a gap

            self._log_every_n = 1000
            self._n_counter = 0

        def reset(self, nominal_period: float):
            self._ma = nominal_period

        async def process_arrival(self, delta_arrival_time: float):

            if delta_arrival_time < self._too_long:
                self._ma = ((1 - self._k) * self._ma) \
                           + (self._k * delta_arrival_time)
                self._n_counter += 1
                if self._n_counter >= self._log_every_n:
                    self._n_counter = 0
                    logger.debug(f"Scale period: {self._ma}")


    # TODO: Deal with connectivity as a mixin

    # For API
    @property
    def connectivity(self):
        if self.is_connected:
            retval = ConnectivityEnum.CONNECTED
        else:
            # intentionally vague, as PUT "connecting" isn't needed
            retval = ConnectivityEnum.NOT_CONNECTED
        return retval

    async def connectivity_setter(self, value: ConnectivityEnum):
        assert isinstance(value, ConnectivityEnum), \
            f"mode of {value} not a ConnectivityEnum " \
            "in Scale.connectivity_setter()"
        if value is ConnectivityEnum.CONNECTED \
                and not self.is_connected:
            await self.connect()
        elif value is ConnectivityEnum.NOT_CONNECTED \
                and self.is_connected:
            await self.disconnect()