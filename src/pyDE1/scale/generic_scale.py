"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import pprint
import time
import warnings
from typing import Optional, Union

import aiosqlite
from bleak.backends.device import BLEDevice

import pyDE1
from pyDE1.bledev.managed_bleak_device import (
    ManagedBleakDevice, ClassChanger, class_changer_generic_class,
)
from pyDE1.config import config
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager.event_manager import SubscribedEvent
from pyDE1.event_manager.events import ConnectivityChange, DeviceRole
from pyDE1.exceptions import (
    DE1NoAddressError,
    DE1RuntimeError, DE1NotConnectedError,
    DE1UnsupportedDeviceError,
)
from pyDE1.scale.events import ScaleWeightUpdate, ScaleTareSeen
from pyDE1.scanner import RegisteredPrefixes

logger = pyDE1.getLogger('Scale')

# Used for class selection and for BLE detection and filtering
_prefix_to_class = dict()


def register_scale_class(cls: 'GenericScale'):
    # logger.warning("This warning doesn't appear")
    if isinstance(cls._supports_prefixes, str):
        # This may not appear in the logs as during import sequence
        logger.error(
            "{}._supports_prefixes should be a list-like iterable, "
            "not a string '{}'".format(cls, cls._supports_prefixes))
        warnings.warn(
            "{}._supports_prefixes should be a list-like iterable, "
            "not a string '{}'".format(cls, cls._supports_prefixes),
            category=RuntimeWarning,
            stacklevel=2
        )
        cls._supports_prefixes = list(cls._supports_prefixes)
    for prefix in cls._supports_prefixes:
        _prefix_to_class[prefix] = cls
        if prefix not in (None, ''):
            RegisteredPrefixes.add_to_role(prefix, DeviceRole.SCALE)
    return cls


def prefix_to_class(prefix: Optional[str]):
    if prefix is None:
        prefix = ''
    cls = None
    try:
        cls = _prefix_to_class[prefix]
    except KeyError:
        if prefix == '':
            raise DE1RuntimeError(
                "Missing empty-string key in _prefix_to_class: "
                f"{_prefix_to_class}")
        for key in _prefix_to_class.keys():
            if key != '' and prefix.startswith(key):
                cls = _prefix_to_class[key]
    if cls is None:
        raise DE1UnsupportedDeviceError(
            f"No recognized scale registered for '{prefix}'")
    return cls


# TODO: Experimentaly confirm that weight and mass-flow estimates
#       are reasonably time aligned - NB: DE1.fall_time

# TODO: Think about how to manage a "tare seen" event
#       and what the use cases for it would be.
#       Could use asyncio.Event(), but what are the states
#       and how do you "release" if it never arrives?

@register_scale_class
@class_changer_generic_class
class GenericScale (ClassChanger, ManagedBleakDevice):
    """
    Rework of Scales -- Generic should be the class initialized,
    changing address with a BLEDevice or connecting may then change
    the class, but shouldn't alter references to the GenericScale API

    NB: Device-specific references may come and go over address changes
    """

    _supports_prefixes = ('',)

    def __init__(self):

        self._role = DeviceRole.SCALE
        self.logger = pyDE1.getLogger('Scale.Generic')
        super(GenericScale, self).__init__()

        self._event_weight_update: SubscribedEvent = SubscribedEvent(self)
        self._event_button_press: SubscribedEvent = SubscribedEvent(self)
        self._event_tare_seen: SubscribedEvent = SubscribedEvent(self)
        self._event_scale_changed: SubscribedEvent = SubscribedEvent(self)

        self._adopt_sync()
        config.logging.handlers.STDERR = 'DEBUG'
        config.logging.formatters.STDERR = config.logging.formatters.LOGFILE
        self._period_estimator = PeriodEstimator(self)

        # Don't need to await this on instantiation
        asyncio.get_event_loop().create_task(
            self._event_weight_update.subscribe(self._self_callback))

    def _adopt_sync(self):
        """
        The "settings" for GenericScale -- split out for reuse in __init__
        """
        self._name: Optional[str] = None

        self._adjust_name_send_scale_change()
        self.logger = pyDE1.getLogger('Scale.Generic')

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

        self._estimated_period = self._nominal_period
        self._last_weight_update_received = 0
        self._last_tare_request_sent = 0

        self._tare_requested = False

        try:
            self._period_estimator.reset(self._nominal_period)
        except AttributeError:
            pass

    async def _adopt_class(self):
        self._adopt_sync()

    @property
    def event_scale_changed(self):
        return self._event_scale_changed

    @property
    def sensor_lag(self):
        return self._sensor_lag

    def _adjust_name_send_scale_change(self):
        # logger.debug(f"Adjusting name {logger.findCaller(stacklevel=2)}")
        try:
            ble_name = self._bleak_client._backend._device_info['Name']
        except (KeyError, AttributeError, TypeError) as e:
            ble_name = '(unknown)'
        self._name = f"{self.__class__.__name__}: {ble_name}"
        sc = ScaleChange(arrival_time=time.time(),
                         state=self.connectivity_state,
                         id=self.address,
                         name=self.name)
        asyncio.create_task(self._event_scale_changed.publish(sc))

    async def _initialize_after_connection(self, hold_ready=False):
        # Check that this is the right class to service the connected device
        self._adjust_name_send_scale_change()
        ble_name = self._bleak_client._backend._device_info['Name']
        cls = prefix_to_class(ble_name)
        if type(self) != cls:
            self.logger.info(
                "Changing class on {} from {} to {} after connection".format(
                    self._name, type(self), cls))
            await self._change_class(cls)
            self._adjust_name_send_scale_change()
        await self.display_on()
        await self.start_sending_weight_updates()
        if self.supports_button_press:
            await self.start_sending_button_updates()
        await self._restore_period_from_db()
        if not hold_ready:
            self._notify_ready()

    async def connect(self):
        """
        TODO: Can this do a "first if found"
            if self.address in (None, '') ??
        """
        # if self.address in (None, ''):
        #     device = await find_first_matching(
        #         recognized_scale_prefixes())
        #     if device:
        #         await self.scale.change_address(device)
        #     else:
        #         raise DE1NoAddressError(
        #             f"Can't connect without an address")
        await self.capture()

    async def disconnect(self):
        await self.release()

    async def start_sending_weight_updates(self):
        raise DE1NotConnectedError

    async def stop_sending_weight_updates(self):
        raise DE1NotConnectedError

    @property
    def is_sending_weight_updates(self):
        raise DE1NotConnectedError

    @property
    def supports_button_press(self):
        return False

    async def start_sending_button_updates(self):
        raise DE1NotConnectedError

    async def stop_sending_button_updates(self):
        raise DE1NotConnectedError

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
        raise DE1NotConnectedError

    async def current_weight(self) -> Optional[float]:
        """
        Intended to request an in-the-moment read from the scale
        If not supported, may return None instead of a weight
        """
        raise DE1NotConnectedError

    async def display_on(self):
        raise DE1NotConnectedError

    async def display_off(self):
        raise DE1NotConnectedError

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

    async def change_address(self, address: Optional[Union[BLEDevice, str]]):
        """
        Change address, including changing type if passed a BLEDevice

        Raises DE1UnsupportedDeviceError if BLEDevice.name is not recognized
        """
        if isinstance(address, BLEDevice) or address in (None, ''):
            if address in (None, ''):
                cls = prefix_to_class('')
            else:
                # This call potentially raises DE1UnsupportedDeviceError
                cls = prefix_to_class(address.name)
            if type(self) != cls:
                self.logger.info(
                    "Address change for {} requested, "
                    "changing class from {} to {}".format(
                        address, type(self), cls))
                if not self.is_released:
                    # TODO: How should a timeout here be handled?
                    #       Should the timeout be configurable?
                    await self.release(
                        timeout=self._bleak_client._backend._timeout)
                await self._change_class(cls)
        changed = await self._bleak_client.change_address(address)
        if changed:
            self._adjust_name_send_scale_change()

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

    async def _self_callback(self, swu: ScaleWeightUpdate) -> None:
        dt = swu.arrival_time - self._last_weight_update_received
        self._last_weight_update_received = swu.arrival_time

        # TODO: Run profiler and evaluate if creating a task
        #       is consuming too much time

        asyncio.create_task(
            self._period_estimator.process_arrival(dt))

        if self._tare_requested:
            dt = swu.arrival_time - self._last_tare_request_sent
            if dt > self._tare_timeout:
                self._tare_requested = False
                logger.error(f"No tare seen after {dt:0.03f} seconds")
            elif abs(swu.weight) < self._tare_threshold:
                self._tare_requested = False
                await self.event_tare_seen.publish(
                    ScaleTareSeen(swu.arrival_time)
                )
                logger.info(f"Tare seen after {dt:0.03f} seconds")

        if self.hold_at_tare:
            if abs(swu.weight) > self._tare_threshold:
                # Timing will be checked in scale.tare()
                await self.tare()

    @property
    def nominal_period(self):
        return self._nominal_period

    @nominal_period.setter
    def nominal_period(self, value):
        self._nominal_period = value
        self._period_estimator.reset(value)

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
                'value': self.estimated_period,
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


class ScaleChange(ConnectivityChange):
    """
    Gets sent when the address of the scale changes "behind the scenes"
    such as with a call to scale.take_over_from()

    Not sent on initialization at this time
    """
    pass


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
        self._scale._estimated_period = nominal_period

    async def process_arrival(self, delta_arrival_time: float):

        if delta_arrival_time < self._too_long:
            self._ma = ((1 - self._k) * self._ma) \
                       + (self._k * delta_arrival_time)
            self._scale._estimated_period = self._ma
            self._n_counter += 1
            if self._n_counter >= self._persist_every_n:
                self._n_counter = 0
                logger.getChild('Period').debug(f"Persisting {self._ma}")
                await self._scale._persist_period_to_db()


