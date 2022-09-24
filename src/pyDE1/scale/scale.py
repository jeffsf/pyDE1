"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import time
from typing import Optional, Callable, Coroutine, Union

import aiosqlite
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTServiceCollection

import pyDE1
import pyDE1.shutdown_manager as sm
from pyDE1.bleak_client_wrapper import BleakClientWrapped
from pyDE1.config import config
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager import SubscribedEvent
from pyDE1.event_manager.events import ConnectivityState, ConnectivityChange
from pyDE1.exceptions import DE1APIValueError, DE1NoAddressError
from pyDE1.scale.events import ScaleWeightUpdate, ScaleTareSeen
from pyDE1.scanner import _registered_ble_prefixes

logger = pyDE1.getLogger('Scale')

# Used for factory and for BLE detection and filtering
_prefix_to_constructor = dict()
_recognized_scale_prefixes = set()


def recognized_scale_prefixes():
    return _recognized_scale_prefixes.copy()

# TODO: Experimentaly confirm that weight and mass-flow estimates
#       are reasonably time aligned - NB: DE1.fall_time

class Scale:

    def __init__(self):
        self._address_or_bledevice: Optional[Union[str, BLEDevice]] = None
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

        self._ready = asyncio.Event()

        self._reconnect_count = 0
        self._log_reconnect_attempts = True

        asyncio.get_event_loop().create_task(
            self._event_connectivity.publish(
                self._connectivity_change(
                    arrival_time=time.time(),
                    state=ConnectivityState.NOT_READY)))

        self._estimated_period = self._nominal_period
        self._last_weight_update_received = 0
        self._last_tare_request_sent = 0

        # See Scale.decommission()
        self._to_decommission = (
            '_event_connectivity',
            '_event_weight_update',
            '_event_button_press',
            '_event_tare_seen',
        )

        # TODO: Think about how to manage a "tare seen" event
        #       and what the use cases for it would be.
        #       Could use asyncio.Event(), but what are the states
        #       and how do you "release" if it never arrives?

        self._tare_requested = False
        self._period_estimator = PeriodEstimator(self)

        # Don't need to await this on instantiation
        asyncio.get_event_loop().create_task(
            self._event_weight_update.subscribe(self._create_self_callback()))


    @property
    def type(self):
        return self.__class__.__name__

    @property
    def address(self):
        addr = self._address_or_bledevice
        if isinstance(addr, BLEDevice):
            addr = addr.address
        return addr

    @address.setter
    def address(self, address: Union[BLEDevice, str]):
        if self.address is not None:
            raise DE1APIValueError(
                "Changing the Scale address is not yet supported")
        self._address_or_bledevice = address
        if isinstance(address, BLEDevice):
            self._name = address.name
        self._bleak_client = BleakClientWrapped(self._address_or_bledevice)

    @property
    def name(self):
        return self._name

    @property
    def sensor_lag(self):
        return self._sensor_lag

    async def connect(self, timeout: Optional[float] = None):

        if timeout is None:
            timeout = config.bluetooth.CONNECT_TIMEOUT

        class_name = type(self).__name__
        if self._log_reconnect_attempts:
            logger.info(f"Connecting to {class_name} at {self.address}")

        assert self._bleak_client is not None

        if not self.is_connected:

            # TODO: Deprecated bleak v0.18.0
            self._bleak_client.set_disconnected_callback(
                self._create_disconnect_callback()
            )

            await asyncio.gather(self._event_connectivity.publish(
                self._connectivity_change(
                    arrival_time=time.time(),
                    state=ConnectivityState.CONNECTING)),
                self._bleak_client.connect(timeout=timeout),
                return_exceptions=True
            )

            if self.is_connected:
                self._address_or_bledevice = self._bleak_client.address
                if self.name is None:
                    self._name = self._bleak_client.name
                logger.info(f"Connected to {class_name} at {self.address}")
                await self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.CONNECTED))
                # This can take some time, potentially delaying DE1 connection
                # At least BlueZ doesn't like concurrent connection requests
                asyncio.create_task(self.standard_initialization())

            else:
                if self._log_reconnect_attempts:
                    logger.error(
                        f"Connection failed to {class_name} at {self.address}")
                await self._notify_not_ready()
                await self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
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
        await self._restore_period_from_db()
        if not hold_notification:
            await self._notify_ready()

    async def _notify_ready(self):
        self._ready.set()
        await self._event_connectivity.publish(
            self._connectivity_change(
                arrival_time=time.time(),
                state=ConnectivityState.READY))
        logger.info("Ready")

    async def _notify_not_ready(self):
        self._ready.clear()
        await self._event_connectivity.publish(
            self._connectivity_change(
                arrival_time=time.time(),
                state=ConnectivityState.NOT_READY))

    @property
    def is_ready(self):
        return self._ready.is_set()

    # Helper method to populate a ConnectivityChange

    def _connectivity_change(self, arrival_time: float,
                             state: ConnectivityState):
        return ConnectivityChange(arrival_time=arrival_time,
                                  state=state,
                                  id=self.address,
                                  name=self.name)

    async def disconnect(self):
        class_name = type(self).__name__
        logger.info(f"Disconnecting from {class_name}")
        if self._bleak_client is None:
            logger.info(f"Disconnecting from {class_name}, no client")
            return

        if self.is_connected:
            await asyncio.gather(
                self._bleak_client.disconnect(),
                self._notify_not_ready(),
                self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.DISCONNECTING)),
                return_exceptions=True
            )

        if self.is_connected:
            logger.error(
                f"Disconnect failed from {class_name} at {self.address}")
            await self._event_connectivity.publish(
                self._connectivity_change(
                    arrival_time=time.time(),
                    state=ConnectivityState.CONNECTED))
        else:
            logger.info(
                f"Scale.disconnect(): Disconnected from {class_name} "
                f"at {self.address}")
            await self._event_connectivity.publish(
                self._connectivity_change(
                    arrival_time=time.time(),
                    state=ConnectivityState.DISCONNECTED))

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

    async def current_weight(self) -> Optional[float]:
        """
        Intended to request an in-the-moment read from the scale
        If not supported, may return None instead of a weight
        """
        raise NotImplementedError

    async def display_on(self):
        raise NotImplementedError

    async def display_off(self):
        raise NotImplementedError

    # The two *_bool for API

    async def tare_with_bool(self, do_it=True):
        if do_it:
            await self.tare()

    async def display_bool(self, on: bool):
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

    def decommission(self):
        # A Scale has several self-references that may prevent GC
        # Rather than try to deal with weakref, just remove the callbacks
        # Oh, and the list of those collbacks!
        logger.info(f'Decommissioning {self} at {self.address}')

        # TODO: Deprecated bleak v0.18.0
        self._bleak_client.set_disconnected_callback(None)
        for break_ref in self._to_decommission:
            setattr(self, break_ref, None)
        self._to_decommission = None

        # logger.debug("Before GC")
        # for ref in gc.get_referrers(self):
        #     logger.info(f"0x{id(self):x} <== {ref}")
        #
        # logger.info(f"0x{id(self):x} is_finalized: {gc.is_finalized(self)}")

    #  disconnected_callback (callable): Callback that will be scheduled in the
    #  event loop when the client is disconnected. The callable must take one
    #  argument, which will be this client object.

    # The callback seems to be expected to be a "plain" function

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
            asyncio.ensure_future(asyncio.gather(
                self._notify_not_ready(),
                scale._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.DISCONNECTED)),
                return_exceptions=True)
            )

            if not client.willful_disconnect:
                asyncio.get_event_loop().create_task(self._reconnect())

        return disconnect_callback

    def _reset_reconnect(self):
        self._reconnect_count = 0
        self._log_reconnect_attempts = True

    async def _reconnect(self):
        """
        Will try immediately config.bluetooth.RECONNECT_RETRY_COUNT times
            of CONNECT_TIMEOUT each. It will then stop logging and retry
            with RECONNECT_GAP seconds in between attempts
        """

        if sm.shutdown_underway.is_set():
            return

        if self._reconnect_count >= config.bluetooth.RECONNECT_RETRY_COUNT:
            await asyncio.sleep(config.bluetooth.RECONNECT_GAP)

        if self._log_reconnect_attempts:
            class_name = type(self).__name__
            logger.info(
                f"Will try reconnecting to {class_name} at {self.address}")

        # Workaround for https://github.com/hbldh/bleak/issues/376
        self._bleak_client.services = BleakGATTServiceCollection()

        await self.connect()
        if self.is_connected:
            self._reset_reconnect()

        else:
            if self._reconnect_count <= config.bluetooth.RECONNECT_RETRY_COUNT:
                self._reconnect_count = self._reconnect_count + 1
            if self._reconnect_count == config.bluetooth.RECONNECT_RETRY_COUNT:
                logger.info("Suppressing further reconnect messages. "
                            "Will keep trying at {}-second intervals.".format(
                    config.bluetooth.RECONNECT_GAP)
                )
                self._log_reconnect_attempts = False
            asyncio.get_event_loop().create_task(
                self._reconnect(), name='ReconnectScale')

    @property
    def nominal_period(self):
        return self._nominal_period

    @nominal_period.setter
    def nominal_period(self, value):
        self._nominal_period = value
        self._period_estimator.reset(self._nominal_period)

    async def _persist_period_to_db(self):
        if not self.address:
            raise DE1NoAddressError(
                "Can't persist scale period without a scale address")
        async with aiosqlite.connect(config.database.FILENAME) as db:
            sql = "INSERT OR REPLACE INTO persist_hkv " \
                  "(header, key, value) " \
                  "VALUES " \
                  "(:header, :key, :value) "
            await db.execute(sql, {
                'header': 'scale.period',
                'key': self.address,
                'value': self.nominal_period,
            })
            await db.commit()

    async def _restore_period_from_db(self):
        if not self.address:
            raise DE1NoAddressError(
                "Can't restore scale period without a scale address")
        async with aiosqlite.connect(config.database.FILENAME) as db:
            sql = "SELECT value FROM persist_hkv " \
                  "WHERE header = :header AND key = :key"
            cur = await db.execute(sql, {
                'header': 'scale.period',
                'key': self.address,
            })
            row = await cur.fetchone()
            if row and row[0]:
                val = float(row[0])
                logger.info(
                    "Loading scale-period estimate of "
                    f"{val:.5f} from database")
                self._estimated_period = val
                self._period_estimator.reset(val)
            else:
                logger.info(
                    "No previous scale-period estimate for "
                    f"{self.address} found")

    # For API
    @property
    def connectivity(self):
        retval = ConnectivityEnum.NOT_CONNECTED
        if self.is_connected:
            if self._ready.is_set():
                retval = ConnectivityEnum.READY
            else:
                retval = ConnectivityEnum.CONNECTED
        return retval

    @staticmethod
    def register_constructor(constructor: Callable, prefix: str):
        _prefix_to_constructor[prefix] = constructor
        _recognized_scale_prefixes.add(prefix)
        _registered_ble_prefixes.add(prefix)


# Used by Scale instances
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

    def __init__(self, my_scale):

        # TODO: How to update this PeriodEstimator for subclass changes?

        self._scale = my_scale

        self._k = 1/10000   # tau ~ 17 min at 10 samples/sec
        self._ma = self._scale.nominal_period
        self._too_long = 0.5  # seconds before considered a gap

        self._persist_every_n = 1000  # about 100 seconds
        self._n_counter = 0

    def reset(self, nominal_period: float):
        self._ma = nominal_period

    async def process_arrival(self, delta_arrival_time: float):

        if delta_arrival_time < self._too_long:
            self._ma = ((1 - self._k) * self._ma) \
                       + (self._k * delta_arrival_time)
            self._scale.nominal_period = self._ma
            self._n_counter += 1
            if self._n_counter >= self._persist_every_n:
                self._n_counter = 0
                logger.getChild('Period').debug(f"Persisting {self._ma}")
                await self._scale._persist_period_to_db()



def scale_factory(ble_device: BLEDevice)-> Scale:
    constructor = None
    try:
        constructor = _prefix_to_constructor[ble_device.name]
    except KeyError:
        for prefix in _prefix_to_constructor.keys():
            if ble_device.name.startswith(prefix):
                constructor = _prefix_to_constructor[prefix]
    if constructor is None:
        raise DE1APIValueError(
            f"No recognized scale registered for {ble_device.name}"
        )
    logger.debug(f"Creating a new instance of {constructor} "
                 f"from {ble_device}")
    scale: Scale = constructor()
    scale.address = ble_device
    return scale


