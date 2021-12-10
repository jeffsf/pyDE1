"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import hashlib
import inspect
import logging
import time
from copy import copy, deepcopy
from typing import Union, Dict, Coroutine, Optional, List, Callable

import aiosqlite
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.backends.service import BleakGATTServiceCollection

import pyDE1.database.insert as db_insert
import pyDE1.de1.handlers
import pyDE1.shutdown_manager as sm
from pyDE1.bleak_client_wrapper import BleakClientWrapped
from pyDE1.config import config
from pyDE1.de1.ble import UnsupportedBLEActionError, CUUID
from pyDE1.de1.c_api import (
    PackedAttr, RequestedState, ReadFromMMR, WriteToMMR, StateInfo,
    FWMapRequest, FWErrorMapRequest, FWErrorMapResponse,
    API_MachineStates, API_Substates, MAX_FRAMES, get_cuuid, MMR0x80LowAddr,
    packed_attr_from_cuuid, pack_one_mmr0x80_write, MMRGHCInfoBitMask,
    CalCommand, CalTargets, Calibration, ShotSettings
)
from pyDE1.de1.events import ShotSampleUpdate, ShotSampleWithVolumesUpdate
from pyDE1.de1.firmware_file import FirmwareFile
from pyDE1.de1.notifications import NotificationState, MMR0x80Data
from pyDE1.de1.profile import (
    Profile, ProfileByFrames, DE1ProfileValidationError, SourceFormat
)
from pyDE1.dispatcher.resource import ConnectivityEnum, DE1ModeEnum
from pyDE1.event_manager import SubscribedEvent
from pyDE1.event_manager.events import (
    ConnectivityState, ConnectivityChange, FirmwareUploadState, FirmwareUpload
)
from pyDE1.exceptions import *
from pyDE1.flow_sequencer import FlowSequencer
from pyDE1.scanner import (
    DiscoveredDevices, BleakScannerWrapped, find_first_matching
)
from pyDE1.singleton import Singleton
from pyDE1.utils import task_name_exists, cancel_tasks_by_name

logger = pyDE1.getLogger('DE1')


class DE1 (Singleton):

    # NB: This is intentionally done in _singleton_init() and not __init__()
    #     See Singleton and Guido's notes there
    #
    #     No parameters are passed as there is no guarantee that any call
    #     will be "the first" call that is the one that initializes
    #
    # def __init__(self):
    #     pass

    def _singleton_init(self):
        self._address_or_bledevice: Optional[Union[str, BLEDevice]] = None
        self._name = None
        self._bleak_client: Optional[BleakClientWrapped] = None

        self._handlers = pyDE1.de1.handlers.default_handler_map(self)

        # TODO: These would benefit from accessor methods
        self._cuuid_dict: Dict[CUUID, NotificationState] = dict()
        self._mmr_dict: Dict[Union[MMR0x80LowAddr, int], MMR0x80Data] = dict()
        # Needs to be consistent with create_Calibration_callback()
        self._cal_factory = CalData()
        self._cal_local = CalData()

        self._latest_profile: Optional[Profile] = None

        self._feature_flag = FeatureFlag(self)

        self._event_connectivity = SubscribedEvent(self)
        self._event_state_update = SubscribedEvent(self)
        self._event_shot_sample = SubscribedEvent(self)
        self._event_water_levels = SubscribedEvent(self)
        self._event_shot_sample_with_volumes_update = SubscribedEvent(self)
        self._event_firmware_upload = SubscribedEvent(self)

        self._ready = asyncio.Event()

        # Used to restrict multiple access to writing the active profile
        self._profile_lock = asyncio.Lock()

        # TODO: Estimate or read this from DE1 when available
        self._line_frequency = config.de1.LINE_FREQUENCY  # Hz

        self._tracking_volume_dispensed = False
        self._volume_dispensed_total = 0
        self._volume_dispensed_preinfuse = 0
        self._volume_dispensed_pour = 0
        self._volume_dispensed_by_frame = []
        # TODO: Convince Ray to return substate and state
        #       in ShotSample so this isn't needed for volume tracking
        self._number_of_preinfuse_frames: int = 0

        self._last_stop_requested = 0

        # Internally in seconds
        self._auto_off_time = None
        # Externally in minutes
        self.auto_off_time = config.de1.DEFAULT_AUTO_OFF_TIME

        self._reconnect_count = 0
        self._log_reconnect_attempts = True

        # Used for volume estimation at this time
        asyncio.create_task(self._event_shot_sample.subscribe(
            self._create_self_callback_ssu()))

        asyncio.create_task(self._sleep_if_bored())

        self.prepare_for_connection(wipe_address=True)
        asyncio.create_task(
            self._event_connectivity.publish(
                self._connectivity_change(arrival_time=time.time(),
                                          state=ConnectivityState.DISCONNECTED))
        )

    #
    # High-level initialization and re-initialization
    #

    def prepare_for_connection(self, wipe_address=True):
        """
        Basically wipe all cached state
        """
        if self.is_connected:
            raise DE1IsConnectedError(
                "Can't prepare_for_connection() while connected.")

        logger.info(
            f"prepare_for_connection(wipe_address={wipe_address})")

        loop = asyncio.get_running_loop()
        if loop is not None and loop.is_running():
            asyncio.create_task(self._notify_not_ready())
        else:
            logger.debug(f"No running loop to _notify_not_ready(): {loop}")

        if wipe_address:
            self._address_or_bledevice = None
            self._bleak_client = None  # Constructor requires an address

        self._cuuid_dict: Dict[CUUID, NotificationState] = dict()
        self._mmr_dict: Dict[Union[MMR0x80LowAddr, int], MMR0x80Data] = dict()
        for cuuid in CUUID:
            self._cuuid_dict[cuuid] = NotificationState(cuuid)
        for mmr in MMR0x80LowAddr:
            self._mmr_dict[mmr] = MMR0x80Data(mmr)

        self._cuuid_dict[CUUID.StateInfo]._last_value = StateInfo(
            State=API_MachineStates.NoRequest,
            SubState=API_Substates.NoState
        )

        self._cal_factory = CalData()
        self._cal_local = CalData()

        self._tracking_volume_dispensed = False
        self._volume_dispensed_total = 0
        self._volume_dispensed_preinfuse = 0
        self._volume_dispensed_pour = 0
        self._volume_dispensed_by_frame = []
        # TODO: Convince Ray to return substate and state
        #       in ShotSample so this isn't needed for volume tracking
        self._number_of_preinfuse_frames: int = 0

        self._latest_profile = None

        self._last_stop_requested = 0

        # Internal flag
        self._recorder_active = False

    async def initialize_after_connection(self):

        logger.info("initialize_after_connection()")

        await asyncio.gather(
            self.start_standard_read_write_notifiers(),
            self.start_standard_periodic_notifiers(),
        )

        t0 = time.time()
        ((event_list, addr_low_list), ignore, ignore, ignore) \
            = await asyncio.gather(
            self.read_standard_mmr_registers(),
            self.read_cuuid(CUUID.StateInfo),
            self.read_cuuid(CUUID.Versions),
            self.read_cuuid(CUUID.ShotSettings),
        )

        event_list.append(self._cuuid_dict[CUUID.StateInfo].ready_event)

        gather_list = [event.wait() for event in event_list]

        logger.info(f"Waiting for {len(event_list)} responses")
        try:
            results = await asyncio.wait_for(asyncio.gather(*gather_list),
                             config.de1.MAX_WAIT_FOR_READY_EVENTS)
            t1 = time.time()
            logger.info(
                f"{len(event_list)} responses received in "
                f"{t1 - t0:.3f} seconds")
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for responses.")
            idx = 0
            for event in event_list:
                event: asyncio.Event
                if not event.is_set():
                    if idx < len(event_list) - 1:
                        failed = MMR0x80LowAddr(addr_low_list[idx])
                        logger.warning(
                            f"No response from #{idx + 1} "
                            f"of {len(event_list)}, " \
                            + str(failed))
                        await self.read_one_mmr0x80(failed)
                    else:
                        logger.warning(
                            "No response from CUUID.StateInfo"
                        )
                        await self.read_cuuid(CUUID.StateInfo)
                idx += 1
            logger.error("Stupidly continuing anyway after re-requesting")

        await FlowSequencer().on_de1_nearly_ready()

        # NB: This gets sent if all there or not
        await self._notify_ready()

        # Don't need to wait on this one
        asyncio.create_task(self.fetch_calibration())

        return

    async def _notify_ready(self):
        self._ready.set()
        await self._event_connectivity.publish(
            self._connectivity_change(arrival_time=time.time(),
                                      state=ConnectivityState.READY))
        logger.info("Ready")

    async def _notify_not_ready(self):
        self._ready.clear()
        await self._event_connectivity.publish(
            self._connectivity_change(arrival_time=time.time(),
                                      state=ConnectivityState.NOT_READY))

    @property
    def is_ready(self):
        return self._ready.is_set()

    @classmethod
    def device_adv_is_recognized_by(cls, device: BLEDevice,
                                    adv: AdvertisementData):
        return adv.local_name == "DE1"

    @property
    def stop_lead_time(self):
        """
        Approximate time from initiation of command to stop flow
        """
        return 0.1  # seconds

    @property
    def fall_time(self):
        """
        Approximate, in-flight time -- 14 cm to cup, 1/2at^2, 170 ms
        """
        return 0.17    # seconds

    @property
    def feature_flag(self):
        return self._feature_flag

    @property
    def feature_flags(self):
        return self._feature_flag.as_dict()

    @property
    def cal_factory(self):
        return copy(self._cal_factory)

    @property
    def cal_local(self):
        return copy(self._cal_local)

    @property
    def address(self):
        addr = self._address_or_bledevice
        if isinstance(addr, BLEDevice):
            addr = addr.address
        return addr

    async def set_address(self, address: Optional[Union[BLEDevice, str]]):
        if address is None:
            await self.disconnect()
            self.prepare_for_connection(wipe_address=True)
        elif address == self.address:
            pass
        else:
            await self.disconnect()
            self.prepare_for_connection(wipe_address=True)
            self._address_or_bledevice = address
            if isinstance(address, BLEDevice):
                self._name = address.name
            self._bleak_client = BleakClientWrapped(self._address_or_bledevice)

    # Helper method to populate a ConnectivityChange

    def _connectivity_change(self, arrival_time: float,
                             state: ConnectivityState):
        return ConnectivityChange(arrival_time=arrival_time,
                                  state=state,
                                  id=self.address,
                                  name=self.name)

    #
    # Self-contained calls for API
    #

    async def first_if_found(self, doit: bool):
        if self.is_connected:
            logger.warning(
                "first_if_found requested, but already connected. "
                "No action taken.")
        elif not doit:
            logger.warning(
                "first_if_found requested, but not True. No action taken.")
        else:
            device = await find_first_matching(('DE1',))
            if device:
                await self.change_de1_to_id(device.address)
        return self.address

    async def change_de1_to_id(self, ble_device_id: Optional[str]):
        """
        For now, this won't return until connected or fails to connect
        As a result, will trigger the timeout on API calls
        """
        logger.info(f"Address change requested for DE1 from {self.address} "
                    f"to {ble_device_id}")

        de1 = DE1()

        # TODO: Need to make distasteful assumption that the id is the address
        try:
            if self.address == ble_device_id:
                logger.info(f"Already using {ble_device_id}. No action taken")
                return
        except AttributeError:
            pass

        if ble_device_id is None:
            # Straightforward request to disconnect and not replace
            await self.set_address(None)

        else:
            ble_device = DiscoveredDevices().ble_device_from_id(ble_device_id)
            if ble_device is None:
                logger.warning(f"No record of {ble_device_id}, initiating scan")
                # NB: find_device_by_filter doesn't add to DiscoveredDevices
                ble_device = await BleakScannerWrapped.find_device_by_address(
                    ble_device_id, timeout=config.bluetooth.CONNECT_TIMEOUT)
            if ble_device is None:
                raise DE1NoAddressError(
                    f"Unable to find device with id: '{ble_device_id}'")
            await self.set_address(ble_device)
            await self.connect()

    @property
    def name(self):
        return self._name

    @property
    def latest_profile(self):
        return deepcopy(self._latest_profile)

    @property
    def event_state_update(self):
        return self._event_state_update

    @property
    def event_shot_sample(self):
        return self._event_shot_sample

    @property
    def event_water_levels(self):
        return self._event_water_levels

    @property
    def event_shot_sample_with_volumes_update(self):
        return self._event_shot_sample_with_volumes_update

    # Deprecated
    @property
    def allow_flow_start_commands(self):
        return not self.feature_flag.ghc_active

    # NB: Linux apparently "needs" a scan when connecting by address
    #     It may be the case that this disconnects other devices
    #     See: https://github.com/hbldh/bleak/issues/361

    async def connect(self, timeout: Optional[float] = None):

        if timeout is None:
            timeout = config.bluetooth.CONNECT_TIMEOUT

        logger.info(f"Connecting to DE1 at {self.address}")

        assert self._bleak_client is not None

        if not self.is_connected:

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
                if self.name is None:
                    self._name = self._bleak_client.name
                logger.info(f"Connected to DE1 at {self.address}")
                await self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.CONNECTED))
                # This can take time, potentially delaying scale connection
                # At least BlueZ doesn't like concurrent connection requests
                asyncio.create_task(self.initialize_after_connection())

            else:
                logger.error(f"Connection failed to DE1 at {self.address}")
                await self._notify_not_ready()
                await self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.DISCONNECTED))

    async def disconnect(self):
        logger.info(f"Disconnecting from DE1")
        if self._bleak_client is None:
            logger.info(f"Disconnecting from DE1, no client")
            return

        if self.is_connected:
            await asyncio.gather(
                self._notify_not_ready(),
                self._bleak_client.disconnect(),
                self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.DISCONNECTING)),
                return_exceptions=True
            )
            if self.is_connected:
                logger.error(
                    f"Disconnect failed from DE1 at {self.address}")
                await self._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.CONNECTED))
            else:
                logger.info("DE1.disconnect(): Disconnected from DE1 at "
                            f"{self.address}")
                await self._event_connectivity.publish(
                    self._connectivity_change(arrival_time=time.time(),
                                              state=ConnectivityState.DISCONNECTED))

    #  disconnected_callback (callable): Callback that will be scheduled in the
    #  event loop when the client is disconnected. The callable must take one
    #  argument, which will be this client object.

    # The callback seems to be expected to be a "plain" function (not awaitable)

    def _create_disconnect_callback(self) -> Callable:
        de1 = self

        def disconnect_callback(client: BleakClientWrapped):
            nonlocal de1
            logger.info(
                "disconnect_callback: "
                f"Disconnected from DE1 at {client.address}, "
                "willful_disconnect: "
                f"{client.willful_disconnect}")

            # asyncio.gather is a Future, not a Task
            asyncio.ensure_future(asyncio.gather(
                self._notify_not_ready(),
                de1._event_connectivity.publish(
                    self._connectivity_change(
                        arrival_time=time.time(),
                        state=ConnectivityState.DISCONNECTED)),
                return_exceptions=True
            ))
            de1.prepare_for_connection(wipe_address=client.willful_disconnect)
            if not client.willful_disconnect:
                # await self._bleak_client.disconnect()
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
            logger.info(
                f"Will try reconnecting to DE1 at {self.address}")

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
                self._reconnect(), name='ReconnectDE1')

    @property
    def is_connected(self):
        if self._bleak_client is None:
            return False
        else:
            return self._bleak_client.is_connected

    async def start_notifying(self, cuuid: CUUID):
        try:
            done = self._cuuid_dict[cuuid].mark_requested()
            await self._bleak_client.start_notify(cuuid.uuid,
                                                  self._handlers[cuuid])
            pyDE1.getLogger(f"DE1.{cuuid.__str__()}").debug("Start notify")
        except KeyError:
            raise DE1NoHandlerError(f"No handler found for {cuuid}")
        return done

    async def stop_notifying(self, cuuid: CUUID):
        try:
            done = self._cuuid_dict[cuuid].mark_ended()
            await self._bleak_client.stop_notify(cuuid.uuid)
            pyDE1.getLogger(f"DE1.{cuuid.__str__()}").debug("Stop notify")
        except KeyError:
            raise DE1NoHandlerError(f"No handler found for {cuuid}")
        return done

    async def start_standard_read_write_notifiers(self):
        await asyncio.gather(
            self.start_notifying(CUUID.Versions),
            self.start_notifying(CUUID.RequestedState),
            self.start_notifying(CUUID.SetTime),
            # self.start_notifying(CUUID.ShotDirectory),
            self.start_notifying(CUUID.ReadFromMMR),
            self.start_notifying(CUUID.WriteToMMR),
            # self.start_notifying(CUUID.ShotMapRequest),
            # self.start_notifying(CUUID.DeleteShotRange),
            self.start_notifying(CUUID.FWMapRequest),
            # self.start_notifying(CUUID.Temperatures),
            self.start_notifying(CUUID.ShotSettings),
            # self.start_notifying(CUUID.Deprecated),
            # self.start_notifying(CUUID.ShotSample),   # periodic
            # self.start_notifying(CUUID.StateInfo),    # periodic
            self.start_notifying(CUUID.HeaderWrite),
            self.start_notifying(CUUID.FrameWrite),
            # self.start_notifying(CUUID.WaterLevels),  # periodic
            self.start_notifying(CUUID.Calibration),
        )
        # As slick as this looks, I haven't been able to resolve
        # the circular import problem with DE1 and MAPPING

        # cuuid_list = list(
        #     get_target_sets(mapping=MAPPING,
        #                     include_can_read=True,
        #                     include_can_write=True, )['PackedAttr'])
        # coro_list = map(lambda pa: self.start_notifying(pa.cuuid), cuuid_list)
        # await asyncio.gather(*coro_list)

    async def start_standard_periodic_notifiers(self):
        """
        Enable the return of read requests from MMR
        as well as the current, periodic reports:
        ShotSample, StateInfo, and WaterLevels
        """
        await asyncio.gather(
            self.start_notifying(CUUID.ShotSample),
            self.start_notifying(CUUID.StateInfo),
            self.start_notifying(CUUID.WaterLevels),
        )

    async def read_cuuid(self, cuuid: CUUID):
        cuuid_logger = pyDE1.getLogger(f"DE1.{cuuid.__str__()}.Read")
        if not cuuid.can_read:
            cuuid_logger.error("Denied read request from non-readable CUUID")
            return None
        cuuid_logger.debug("Requested")
        # self._cuuid_dict[cuuid].mark_requested()  # TODO: This isn't ideal

        # I wish I knew why there isn't an innate timeout for most asyncio
        async def _read_cuuid_inner():
            async with cuuid.lock:
                return await self._bleak_client.read_gatt_char(cuuid.uuid)

        if cuuid.lock.locked():
            cuuid_logger.warning(f"Awaiting lock to read {cuuid.name}")

        try:
            wire_bytes = await asyncio.wait_for(
                _read_cuuid_inner(),
                timeout=config.de1.CUUID_LOCK_WAIT_TIMEOUT)
        except asyncio.TimeoutError as e:
            cuuid_logger.critical(
                "Timeout waiting for lock. Aborting process.")
            raise e

        obj = packed_attr_from_cuuid(cuuid, wire_bytes)
        self._cuuid_dict[cuuid].mark_updated(obj)
        return obj

    async def write_packed_attr(self, obj: PackedAttr, have_lock=False):
        cuuid = get_cuuid(obj)
        cuuid_logger = pyDE1.getLogger(f"DE1.{cuuid.__str__()}.Write")

        # See write_packed_attr_return_notification() which acquires the lock
        # Presently only used for FWMapRequest and Calibration
        # to ensure ready for firmware upload

        if have_lock:
            cuuid_logger.info(obj.log_string())
            await self._bleak_client.write_gatt_char(cuuid.uuid,
                                                     obj.as_wire_bytes())
        else:
            # I wish I knew why there isn't an innate timeout for most asyncio
            async def _write_packed_attr_inner():
                async with cuuid.lock:
                    cuuid_logger.info(obj.log_string())
                    await self._bleak_client.write_gatt_char(
                        cuuid.uuid, obj.as_wire_bytes())

            if cuuid.lock.locked():
                cuuid_logger.warning(f"Awaiting lock to write {cuuid.name}")

            try:
                await asyncio.wait_for(
                    _write_packed_attr_inner(),
                    timeout=config.de1.CUUID_LOCK_WAIT_TIMEOUT)
            except asyncio.TimeoutError as e:
                cuuid_logger.critical(
                    "Timeout waiting for lock. Aborting process.")
                raise e

        # Read-back ensures that local cache is consistent
        if isinstance(obj, WriteToMMR) and obj.addr_high == 0x80:
            try:
                addr = MMR0x80LowAddr(obj.addr_low)
                if addr.can_read:
                    wait_for = self.read_one_mmr0x80_and_wait(addr)
                else:
                    wait_for = None
            except ValueError:
                # Not a known addr, so not readable
                wait_for = None

        elif cuuid.can_read and cuuid not in (
                CUUID.RequestedState,   # Comes back in StateInfo
                CUUID.WriteToMMR,       # Decode not implemented
                CUUID.HeaderWrite,      # Decode not implemented
                CUUID.FrameWrite,       # Decode not implemented
                CUUID.Calibration,      # Comes back as a notification
        ):
            wait_for = self.read_cuuid(cuuid)

        else:
            wait_for = None

        if wait_for is not None:
            await wait_for

    # This was previously only used for the MMR FMMapRequest

    async def write_packed_attr_return_notification(self, obj: PackedAttr):
        """
        Write to the CUUID, then wait for the first response

        This is unsafe right now if not notifying already
        or if on a CUUID that doesn't notify after a write
        either in general, or due to an unrecognized command.

        This also isn't robust to overlapping requests

        TODO: Consider how to handle multi-packet requests (MMR)
              and what "done" means in that case
        """
        cuuid = get_cuuid(obj)
        cuuid_logger = pyDE1.getLogger(f"DE1.{cuuid.__str__()}")
        if not cuuid.can_write_then_return:
            raise UnsupportedBLEActionError(
                "write_cuuid_return_notification not supported for "
                + cuuid.__str__()
            )
        cuuid_logger.debug(f"Acquiring write/notify lock")

        async def _write_packed_attr_return_notification_inner():
            async with cuuid.lock:
                cuuid_logger.info("Acquired write/notify lock")
                # TODO: This order should work, though potential race condition
                notification_state = self._cuuid_dict[cuuid]
                await self.write_packed_attr(obj, have_lock=True)
                notification_state.mark_requested()
                cuuid_logger.debug("Waiting for notification")
                await notification_state.ready_event.wait()
                cuuid_logger.debug("Returning notification")
                return notification_state.last_value

        if cuuid.lock.locked():
            cuuid_logger.warning(
                f"Awaiting lock to write and return {cuuid.name}")

        try:
            retval = await asyncio.wait_for(
                _write_packed_attr_return_notification_inner(),
                timeout=config.de1.CUUID_LOCK_WAIT_TIMEOUT)
        except asyncio.TimeoutError as e:
            cuuid_logger.critical(
                "Timeout waiting for lock. Aborting process.")
            raise e

        return retval

    async def _request_state(self, State: API_MachineStates):
        rs = RequestedState(State)
        await self.write_packed_attr(rs)

    # TODO: Should this be public or private?
    #       Revisit if cleaning up MMR/CUUID internals
    async def read_mmr(self, length, addr_high, addr_low, data_bytes=b''
                       ) -> List[asyncio.Event]:
        mmr = ReadFromMMR(Len=length, addr_high=addr_high, addr_low=addr_low,
                          Data=data_bytes)
        ready_events = list()
        if addr_high == 0x80:
            #
            # TODO: Revisit this if refactoring
            #
            # The stride of MMR0x80Data is going to be 4 bytes except
            # in the debug log region, where it will be 16 bytes
            #
            # There is the possibility of moving from one region to another
            # that is not accounted for here
            #
            if mmr.is_within_debug_log:
                stride = 16
            else:
                stride = 4
            request_time = time.time()
            for addr in range(addr_low, (addr_low + (mmr.Len + 1) * 4), stride):
                if addr not in self._mmr_dict:
                    self._mmr_dict[addr] = MMR0x80Data(addr)
                ready_events.append(
                    self._mmr_dict[addr].mark_requested(request_time)
                )
        await self.write_packed_attr(mmr)
        return ready_events

    async def read_one_mmr0x80(self, mmr0x80: MMR0x80LowAddr) -> asyncio.Event:
        ready_events = await self.read_mmr(
            length=0,
            addr_high=0x80,
            addr_low=mmr0x80
        )
        return ready_events[0]

    # TODO: Think through all of this as it applies to PATCH
    async def read_one_mmr0x80_and_wait(self, mmr0x80: MMR0x80LowAddr) -> None:
        ready_event = await self.read_one_mmr0x80(mmr0x80)
        await ready_event.wait()

    async def write_one_mmr0x80(self, mmr0x80: MMR0x80LowAddr,
                                value: Union[int, float]):
        await self.write_packed_attr(pack_one_mmr0x80_write(
            MMR0x80LowAddr.FLUSH_TIMEOUT, value))

#
# MMR-based properties
#

    async def read_standard_mmr_registers(self) -> (List[asyncio.Event],
                                                    List[MMR0x80LowAddr]):
        """
        Request a read of the readable MMR registers, in bulk

        Read and wait for MMR0x80LowAddr.CPU_FIRMWARE_BUILD so that
        feature_flag can be used to determine "safe" reads
        """

        await self.read_one_mmr0x80_and_wait(MMR0x80LowAddr.CPU_FIRMWARE_BUILD)

        start_block_1 = MMR0x80LowAddr.HW_CONFIG
        end_block_1 = MMR0x80LowAddr.V13_MODEL
        words_block_1 = int((end_block_1 - start_block_1) / 4)

        # Always skip the debug log region

        if self.feature_flag.safe_to_read_mmr_continuous:

            start_block_2 = MMR0x80LowAddr.FAN_THRESHOLD
            end_block_2 = self.feature_flag.last_mmr0x80
            words_block_2 = int((end_block_2 - start_block_2) / 4)

            start_block_3 = None
            end_block_3 = None
            words_block_3 = 0

        else:

            # Certain firmware versions will hang if an attempt is made
            # to read PREF_GHC_MCI or MAX_SHOT_PRESS

            start_block_2 = MMR0x80LowAddr.FAN_THRESHOLD
            end_block_2 = MMR0x80LowAddr.GHC_INFO
            words_block_2 = int((end_block_2 - start_block_2) / 4)

            start_block_3 = MMR0x80LowAddr.TARGET_STEAM_FLOW
            end_block_3 = self.feature_flag.last_mmr0x80
            words_block_3 = int((end_block_3 - start_block_3) / 4)

        # Generated "bleak.exc.BleakDBusError: org.bluez.Error.InProgress"
        # from assert_reply in write_gatt_char in block_3 write
        #
        # Not clear if this is by adapter, device, or characteristic
        #
        # await asyncio.gather(
        #     self.read_mmr(words_block_1 - 1, 0x80, start_block_1),
        #     self.read_mmr(words_block_2 - 1, 0x80, start_block_2),
        #     self.read_mmr(words_block_3 - 1, 0x80, start_block_3),
        # )

        event_list = await self.read_mmr(
            words_block_1, 0x80, start_block_1)
        event_list.extend(await self.read_mmr(
            words_block_2, 0x80, start_block_2))
        if words_block_3:
            event_list.extend(await self.read_mmr(
                words_block_3, 0x80, start_block_3))

        addr_low_list = []
        addr_low_list.extend(range(start_block_1, end_block_1 + 4, 4))
        addr_low_list.extend(range(start_block_2, end_block_2 + 4, 4))
        if words_block_3:
            addr_low_list.extend(range(start_block_3, end_block_3 + 4, 4))

        return event_list, addr_low_list



    #
    # Upload a shot profile
    #

    # API version

    async def upload_json_v2_profile(self, profile: Union[bytes,
                                                          bytearray,
                                                          str]):
        pbf = ProfileByFrames().from_json(profile)
        await self.upload_profile(pbf)
        async with aiosqlite.connect(config.database.FILENAME) as db:
            await db_insert.profile(pbf, db, time.time())
            logger.info("Returned from db insert")

    # "Internal" version

    async def upload_profile(self, profile: ProfileByFrames,
                             force=True):
        try:
            osl = FlowSequencer().profile_can_override_stop_limits(
                API_MachineStates.Espresso
            )
            ott = FlowSequencer().profile_can_override_tank_temperature(
                API_MachineStates.Espresso
            )
        except AttributeError:
            raise DE1APIAttributeError(
                "Profile upload called without a FlowSequencer. Not uploading")

        if task_name_exists('upload_profile'):
            if force:
                logger.warning('Profile upload in progress being canceled')
                await self.cancel_profile_upload()
            else:
                raise DE1OperationInProgressError(
                    'There is already a profile upload in progress')
        profile_upload_stopped = asyncio.Event()
        upload_task = asyncio.create_task(self._upload_profile(
            profile=profile,
            override_stop_limits=osl,
            override_tank_temperature=ott,
            profile_upload_stopped=profile_upload_stopped)
        )
        await profile_upload_stopped.wait()
        if (e := upload_task.exception()) is not None:
            logger.info(f"Upload task exception: {upload_task.exception()}")
            raise e


    @staticmethod
    async def cancel_profile_upload():
        cancel_tasks_by_name('upload_profile')

    async def _upload_profile(self, profile: ProfileByFrames,
                              override_stop_limits,
                              override_tank_temperature,
                              profile_upload_stopped: asyncio.Event):

        try:
            if not profile.validate():
                raise DE1ProfileValidationError

            # async with asyncio.wait_for(
            #     self._profile_lock.acquire(), timeout=3):
            # TODO: Should there be some way to acquire lock on the two CUUIDs?

            async with self._profile_lock:

                for cuuid in (CUUID.HeaderWrite, CUUID.FrameWrite):
                    if not self._cuuid_dict[cuuid].is_notifying:
                        done = await self.start_notifying(cuuid)
                        # await done.wait()

                self._latest_profile = None
                bytes_for_fingerprint = bytearray()

                await self.write_packed_attr(profile.header_write())
                bytes_for_fingerprint += profile.header_write().as_wire_bytes()
                for frame in profile.shot_frame_writes():
                    await self.write_packed_attr(frame)
                    bytes_for_fingerprint += frame.as_wire_bytes()
                for frame in profile.ext_shot_frame_writes():
                    await self.write_packed_attr(frame)
                    bytes_for_fingerprint += frame.as_wire_bytes()
                await self.write_packed_attr(profile.shot_tail_write())
                bytes_for_fingerprint \
                    += profile.shot_tail_write().as_wire_bytes()

                profile._fingerprint = hashlib.sha1(
                    bytes_for_fingerprint).hexdigest()

                if profile.number_of_preinfuse_frames is not None:
                    self._number_of_preinfuse_frames = \
                        profile.number_of_preinfuse_frames

                if profile.tank_temperature is not None \
                    and override_tank_temperature:
                    await self.write_and_read_back_mmr0x80(
                        addr_low=MMR0x80LowAddr.TANK_TEMP,
                        value=profile.tank_temperature
                    )

                if override_stop_limits:

                    if (target := profile.target_volume) is not None:
                        if target <= 0:
                            target = None
                        FlowSequencer().stop_at_volume_set(
                            state=API_MachineStates.Espresso,
                            volume=target
                        )

                    if (target := profile.target_weight) is not None:
                        if target <= 0:
                            target = None
                        FlowSequencer().stop_at_weight_set(
                            state=API_MachineStates.Espresso,
                            weight=target
                        )

                self._latest_profile = profile

        except asyncio.CancelledError:
            pass
        finally:
            profile_upload_stopped.set()

    async def write_and_read_back_mmr0x80(self, addr_low: MMR0x80LowAddr,
                                          value: float):
        if not addr_low.can_write:
            raise DE1APIValueError(
                f"MMR target address not writable: {addr_low.__repr__()}")
        if not addr_low.can_read:
            raise DE1APIValueError(
                f"MMR target address not readable: {addr_low.__repr__()}")

        mmr_record = self._mmr_dict[addr_low]

        if mmr_record.last_requested is None:
            await self.read_one_mmr0x80(addr_low)
        if not mmr_record.ready_event.is_set():
            logger.info(f"About to wait for {addr_low.__repr__()}")
        await mmr_record.ready_event.wait()

        # old = mmr_record.data_decoded
        # value = (old + 0.1) % 20
        # logger.info(f"old and new t: {old} {value}")

        if value != mmr_record.data_decoded:
            pa = pack_one_mmr0x80_write(addr_low,
                                        value)
            await self.write_packed_attr(pa)

            # Queue a read-back to update DE1
            asyncio.create_task(
                self.read_one_mmr0x80(addr_low))

    #
    # Firmware updating
    #

    # TODO: Does it need an explicit lock
    #       or is the presence of the process "safe enough"?

    async def upload_firmware_from_content(self,
                                           content: Union[bytes, bytearray]):
        fw = FirmwareFile(content=content)
        await self.upload_firmware(fw)

    @property
    def uploading_firmware(self):
        return task_name_exists('upload_firmware')

    async def cancel_firmware_api(self, val):
        """
        Ignores the value, always tries to cancel
        """
        if not self.uploading_firmware:
            raise DE1OperationInProgressError(
                "No 'upload_firmware' task to cancel"
            )
        await self.cancel_firmware_upload()

    async def upload_firmware(self, fw: FirmwareFile, force=False, wait=False):
        if self.uploading_firmware:
            if force:
                logger.warning('Firmware upload in progress being canceled')
                await self.cancel_firmware_upload()
            else:
                raise DE1OperationInProgressError
        t = asyncio.create_task(self._upload_firmware(fw),
                                name='upload_firmware')
        # t.add_done_callback()
        logger.info(f"Firmware upload started for {fw.filename}")
        if wait:
            await t
        return t

    async def cancel_firmware_upload(self):
        cancel_tasks_by_name('upload_firmware')
        await self._event_firmware_upload.publish(
            FirmwareUpload(arrival_time=time.time(),
                           state=FirmwareUploadState.CANCELED,
                           uploaded=0,
                           total=0))

    async def _upload_firmware(self, fw: FirmwareFile, sleep=False):
        start_addr = 0x000000
        write_size = 0x10
        bytes_written = 0
        bytes_to_write = len(fw.content)
        offsets = range(0, bytes_to_write, write_size)

        last_notified = 0
        NOTIFY_EVERY = 1024  # bytes

        if sleep:  # de1app sleeps, it doesn't handle concurrency well
            await self._request_state(API_MachineStates.Sleep)

        await self._event_firmware_upload.publish(
            FirmwareUpload(arrival_time=time.time(),
                           state=FirmwareUploadState.STARTING,
                           uploaded=bytes_written,
                           total=bytes_to_write))

        await self.start_notifying(CUUID.FWMapRequest)

        fw_map_result = await self.write_packed_attr_return_notification(
            FWMapRequest(
                WindowIncrement=0,
                FWToErase=1,
                FWToMap=1,
                FirstError=FWErrorMapRequest.Ignore
            )
        )

        for offset in offsets:
            data = fw.content[offset:(offset + write_size)]
            await self.write_packed_attr(
                WriteToMMR(
                    Len=len(data),
                    Address=(start_addr + offset),
                    Data=data,
                )
            )
            bytes_written += write_size

            if bytes_written >= last_notified + NOTIFY_EVERY:
                await self._event_firmware_upload.publish(
                    FirmwareUpload(arrival_time=time.time(),
                                   state=FirmwareUploadState.UPLOADING,
                                   uploaded=bytes_written,
                                   total=bytes_to_write))
                last_notified = bytes_written

        # Always send the "100%" report
        if bytes_written != last_notified:
            await self._event_firmware_upload.publish(
                FirmwareUpload(arrival_time=time.time(),
                               state=FirmwareUploadState.UPLOADING,
                               uploaded=bytes_written,
                               total=bytes_to_write))

        # TODO: Is there something better here?
        await asyncio.sleep(1)

        fw_map_result = await self.write_packed_attr_return_notification(
            FWMapRequest(
                WindowIncrement=0,
                FWToErase=0,
                FWToMap=1,
                FirstError=FWErrorMapRequest.ReportFirst
            )
        )

        success =  fw_map_result.FirstError == FWErrorMapResponse.NoneFound
        if success:
            result = FirmwareUploadState.COMPLETED
        else:
            result = FirmwareUploadState.FAILED
            logger.error(
                "Error(s) in firmware upload. "
                f"First at 0x{fw_map_result.FirstError:06x}"
            )

        await self._event_firmware_upload.publish(
            FirmwareUpload(arrival_time=time.time(),
                           state=result,
                           uploaded=bytes_written,
                           total=bytes_to_write))

        return success

        #
        # I couldn't get this to work, always getting "stuck" on the first addr
        # even when patching with a single-packet upload.
        # Leaving it here for reference -- 2021-05-25
        #

        #
        # Fill in any gaps
        #

        # count_limit = 10
        # count = 0
        # retval = False
        #
        # done = fw_map_result.FirstError == FWErrorMapResponse.NoneFound
        #
        # while not done:
        #     fw_map_result = await self.write_cuuid_return_notification(
        #         CUUID.FWMapRequest, FWMapRequest(
        #             WindowIncrement=0,
        #             FWToErase=0,
        #             FWToMap=1,
        #             FirstError=FWErrorMapRequest.ReportNext
        #         )
        #     )
        #     count += 1
        #     done = (fw_map_result.FirstError == FWErrorMapResponse.NoneFound
        #             or count > count_limit)
        #
        # while count < count_limit:
        #     fw_map_result = await self.write_cuuid_return_notification(
        #         CUUID.FWMapRequest, FWMapRequest(
        #             WindowIncrement=0,
        #             FWToErase=0,
        #             FWToMap=1,
        #             FirstError=FWErrorMapRequest.ReportFirst
        #         )
        #     )
        #     logger.debug(f"Report first: {fw_map_result.log_string()}")
        #     fix_addr = fw_map_result.FirstError
        #     if fix_addr == FWErrorMapResponse.NoneFound:
        #         retval = True
        #         break
        #     while count < count_limit:
        #         count += 1
        #         offset = fix_addr - start_addr
        #         data = fw.file_contents[offset:(offset + write_size)]
        #         await self.write_cuuid(
        #             CUUID.WriteToMMR, WriteToMMR(
        #                 Len=len(data),
        #                 Address=(start_addr + offset),
        #                 Data=data,
        #             )
        #         )
        #         fw_map_result = await self.write_cuuid_return_notification(
        #             CUUID.FWMapRequest, FWMapRequest(
        #                 WindowIncrement=0,
        #                 FWToErase=0,
        #                 FWToMap=1,
        #                 FirstError=FWErrorMapRequest.ReportNext
        #             )
        #         )
        #         logger.debug(f"Report next: {fw_map_result.log_string()}")
        #         fix_addr = fw_map_result.FirstError
        #         if fix_addr == FWErrorMapResponse.NoneFound:
        #             break
        #
        # return retval

    @property
    def current_state(self) -> API_MachineStates:
        return self._cuuid_dict[CUUID.StateInfo].last_value.State

    @property
    def state_last_updated(self) -> Optional[float]:
        # Time in seconds
        return self._cuuid_dict[CUUID.StateInfo].last_updated

    @property
    def current_substate(self) -> API_Substates:
        return self._cuuid_dict[CUUID.StateInfo].last_value.SubState

    # Perhaps one day line frequency will be reported by the firmware
    # Needed for volume estimation

    @property
    def line_frequency(self) -> int:
        return self._line_frequency

    @line_frequency.setter
    def line_frequency(self, value):
        if value not in [50, 60]:
            raise DE1APIValueError(f"Line frequency must be 50 or 60 ({value})")
        self._line_frequency = value

    # Perhaps one day volume dispensed will be tracked by the firmware

    @property
    def volume_dispensed_preinfuse(self):
        return self._volume_dispensed_preinfuse

    @property
    def volume_dispensed_pour(self):
        return self._volume_dispensed_pour

    @property
    def volume_dispensed_total(self):
        return self._volume_dispensed_total

    @property
    def volume_dispensed_by_frame(self):
        """
        A list of estimated volume dispensed by frame
        """
        return copy(self._volume_dispensed_by_frame)

    def _reset_volume_dispensed(self):
        self._volume_dispensed_preinfuse = 0
        self._volume_dispensed_pour = 0
        self._volume_dispensed_total = 0
        self._volume_dispensed_by_frame = [0] * MAX_FRAMES

    def _create_self_callback_ssu(self) -> Coroutine:
        de1 = self
        last_sample_time = 0
        start_up = True

        async def de1_self_callback(ssu: ShotSampleUpdate):
            nonlocal de1, last_sample_time, start_up

            # Track volume dispensed

            # TODO: Reconstruct original DE1 clock prior to EventPayload

            # sample time is counts of half-cycles in a 16-bit unsigned int
            # Expect 25 if nothing is missed, 4 per second on 50 Hz, ~5 on 60
            if start_up:
                start_up = False
            else:
                t_inc = ssu.sample_time - last_sample_time
                if t_inc < 0:
                    t_inc += 65536
                use_this = False
                if 24 < t_inc < 26:
                    use_this = True
                elif 49 < t_inc < 51:
                    use_this = True
                    logger.warning(
                        f"Skipped update at {t_inc} samples? {ssu}"
                    )
                else:
                    use_this = False
                    # Changed to warning (from error) here as seems to happen
                    # around state change reports and heavy BLE traffic
                    logger.warning(
                        f"Unexpected update period {t_inc} from {ssu}"
                    )

                if use_this and de1._tracking_volume_dispensed:
                    v_inc = ssu.group_flow * t_inc / (de1.line_frequency * 2)
                    # since de1.volume_dispensed creates a copy,
                    # and this should be the only "writer" other than clear
                    # don't use a lock

                    # TODO: Convince Ray to return substate and state
                    #       in ShotSample so don't need to use frame count
                    #       (also could help with the missed-Idle de1app bug)
                    if ssu.frame_number > de1._number_of_preinfuse_frames:
                        de1._volume_dispensed_pour += v_inc
                    else:
                        de1._volume_dispensed_preinfuse += v_inc
                    de1._volume_dispensed_total += v_inc
                    if de1.current_state is API_MachineStates.Espresso:
                        to_frame = ssu.frame_number
                    else:
                        to_frame = 0
                    de1._volume_dispensed_by_frame[to_frame] += v_inc

            last_sample_time = ssu.sample_time

            await de1._event_shot_sample_with_volumes_update.publish(
                ShotSampleWithVolumesUpdate(
                    ssu,
                    volume_preinfuse=self._volume_dispensed_preinfuse,
                    volume_pour=self._volume_dispensed_pour,
                    volume_total=self._volume_dispensed_total,
                    volume_by_frame=self._volume_dispensed_by_frame,
                )
            )

        return de1_self_callback

    async def fetch_calibration(self):
        for tgt in (CalTargets.CalFlow,
                       CalTargets.CalPressure,
                       CalTargets.CalTemp):
            for cmd in (CalCommand.Read, CalCommand.ReadFactory):
                req = Calibration(WriteKey=0,
                                  CalCommand=cmd,
                                  CalTarget=tgt,
                                  DE1ReportedValue=0,
                                  MeasuredVal=0
                                  )
                retval = await self.write_packed_attr_return_notification(req)

    async def skip_to_next(self):
        """
        Requests the next frame if in Espresso mode.

        Tries to go to Idle in other modes
        """
        was_espresso = self.current_state == API_MachineStates.Espresso
        await self._request_state(API_MachineStates.SkipToNext)
        if was_espresso:
            logger.info("Skip to next request made")
        else:
            logger.warning(
                "Skip to next request granted while in "
                f"{self.current_state.name}")

    async def stop_flow(self):
        """
        If in a flow state, request stopping flow
        Replaces legacy "go to Idle"
        """
        # TODO Can the logic around "already asked, wait a bit" be cleaned up?
        logger.info("stop_flow() called")
        reasonable_stop_time = 0.25  # seconds after request
        if self.current_state.is_flow_state \
                and self.current_substate.flow_phase in ['before', 'during'] \
                and (now := time.time() - self._last_stop_requested) \
                    > reasonable_stop_time:
            self._last_stop_requested = now
            await self._request_state(API_MachineStates.Idle)

    async def end_steam(self):
        """
        If steaming active, put into "puff" mode
        """
        logger.info("end_steam() called")
        log_level = None
        cs = self.current_state
        css = self.current_substate
        if cs is API_MachineStates.Steam:
                if css in (API_Substates.Pour,):
                    current_shot_settings: ShotSettings = self._cuuid_dict[
                        CUUID.ShotSettings].last_value
                    temp_shot_settings: ShotSettings = deepcopy(
                        current_shot_settings)
                    temp_shot_settings.TargetSteamLength = 0
                    await self.write_packed_attr(temp_shot_settings)
                    logger.debug("Wrote zero-time to steam length")
                    await self.write_packed_attr(current_shot_settings)
                    tsl = current_shot_settings.TargetSteamLength
                    logger.debug(f"Restored {tsl} to steam length")
                else:
                    log_level = logging.WARNING
        else:
            log_level = logging.ERROR

        if log_level is not None:
            logger.log(
                log_level,
                f"end_steam() called during {cs},{css}, no action taken")


    async def idle(self):
        """
        This is an explicit request for Idle.

        de1.stop_flow() is probably more appropriate in many cases
        """
        logger.info("idle() called")
        await self._request_state(API_MachineStates.Idle)

    async def sleep(self):
        logger.info("sleep() called")
        if self.current_state not in (API_MachineStates.Idle,
                                      API_MachineStates.GoingToSleep,
                                      API_MachineStates.Refill):
            logger.warning(
                "Sleep requested while in {}, {}. Calling idle() first.".format(
                    self.current_state.name, self.current_substate.name
                ))
            await self.idle()
            # TODO: Really should wait here until Idle seen
            #       If so, how to deal with it if it doesn't idle soon?
        await self._request_state(API_MachineStates.Sleep)

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

    async def connectivity_setter(self, value):
        assert isinstance(value, ConnectivityEnum), \
            f"mode of {value} not a ConnectivityEnum "
        if value is ConnectivityEnum.CONNECTED:
            await self.connect()
        elif value is ConnectivityEnum.NOT_CONNECTED:
            await self.disconnect()
        else:
            raise DE1APIValueError(
                "Only CONNECTED and NOT_CONNECTED can be set, "
                f"not {value}")

    @property
    def auto_off_time(self):
        if self._auto_off_time:
            return self._auto_off_time / 60
        else:
            return None

    @auto_off_time.setter
    def auto_off_time(self, t_minutes):
        if not t_minutes:
            self._auto_off_time = None
        elif t_minutes < 0:
            raise DE1APIValueError(
                f"auto_off_time must be non-negative or None, not {t_minutes}")
        else:
            self._auto_off_time = t_minutes * 60

    # Non-GHC only -- no checking for GHC presence at this level

    async def _flow_start_espresso(self):
        await self.write_packed_attr(RequestedState(
            State=API_MachineStates.Espresso))

    async def _flow_start_hot_water_rinse(self):
        await self.write_packed_attr(RequestedState(
            State=API_MachineStates.HotWaterRinse))

    async def _flow_start_steam(self):
        await self.write_packed_attr(RequestedState(
            State=API_MachineStates.Steam))

    async def _flow_start_hot_water(self):
        await self.write_packed_attr(RequestedState(
            State=API_MachineStates.HotWater))

    # General mode activation -- check is here for GHC or not

    @property
    def state_getter(self):
        return {
            'state': self.current_state.name,
            'substate': self.current_substate.name,
        }

    async def mode_setter(self, mode: DE1ModeEnum):
        assert isinstance(mode, DE1ModeEnum), \
            f"mode of {mode} not a DE1ModeEnum in DE1.mode_setter()"

        # Ensure GHC data has been read
        if self._mmr_dict[MMR0x80LowAddr.GHC_INFO].data_decoded is None:
            logger.info("GHC_INFO not present, reading now.")
            await self.read_one_mmr0x80_and_wait(MMR0x80LowAddr.GHC_INFO)

        cs = self.current_state
        if cs == API_MachineStates.NoRequest:
            logger.warning(f"Refreshing current state as is NoRequest")
            await self.read_cuuid(CUUID.StateInfo)
            cs = self.current_state
        css = self.current_substate
        logger.debug(f"Request to change mode to {mode} "
                     f"while in {API_MachineStates(cs).name}")

        if mode is DE1ModeEnum.SLEEP:
            logger.debug(f"current state: {cs}, {type(cs)}")
            if cs in (API_MachineStates.Idle,
                      API_MachineStates.Refill):
                logger.debug("API triggered sleep()")
                await self.sleep()
            elif self.current_state in (API_MachineStates.Sleep,
                                        API_MachineStates.GoingToSleep):
                pass
            else:
                raise DE1APIUnsupportedStateTransitionError(mode, cs, css)

        elif mode is DE1ModeEnum.WAKE:
            if cs in (API_MachineStates.Sleep,
                      API_MachineStates.GoingToSleep):
                logger.debug("API triggered idle()")
                await self.idle()
            else:
                pass

        elif mode is DE1ModeEnum.STOP:
            override_checks = False
            if cs in (API_MachineStates.Sleep,
                      API_MachineStates.GoingToSleep,
                      API_MachineStates.SchedIdle,
                      API_MachineStates.Idle):
                if config.de1.API_STOP_IGNORES_CHECKS:
                    override_checks = True
                else:
                    pass
            elif cs in (API_MachineStates.ShortCal,
                        API_MachineStates.SelfTest,
                        API_MachineStates.LongCal,
                        API_MachineStates.FatalError,
                        API_MachineStates.Init,
                        API_MachineStates.NoRequest,
                        API_MachineStates.SkipToNext,
                        API_MachineStates.Refill,
                        API_MachineStates.InBootLoader):
                if config.de1.API_STOP_IGNORES_CHECKS:
                    override_checks = True
                else:
                    raise DE1APIUnsupportedStateTransitionError(mode, cs, css)
            else:
                logger.debug("API triggered idle()")
                await self.idle()
            if override_checks:
                logger.warning(
                    "API_STOP_IGNORES_CHECKS triggered idle() during "
                    f"{cs},{css}")
                await self.idle()

        elif mode is DE1ModeEnum.SKIP_TO_NEXT:
            if cs == API_MachineStates.Espresso \
                and self.current_substate in (API_Substates.PreInfuse,
                                              API_Substates.Pour):
                logger.debug("API triggered skip_to_next()")
                await self.skip_to_next()
            else:
                raise DE1APIUnsupportedStateTransitionError(mode, cs, css)

        elif mode is DE1ModeEnum.END_STEAM:
            if cs == API_MachineStates.Steam:
                if self.current_substate in (API_Substates.Pour,):
                    logger.debug("API triggered end_steam() for END_STEAM")
                    await self.end_steam()
                else:
                    logger.debug("API triggered stop_flow() for END_STEAM")
                    await self.stop_flow()


        elif mode in (DE1ModeEnum.ESPRESSO,
                      DE1ModeEnum.HOT_WATER_RINSE,
                      DE1ModeEnum.STEAM,
                      DE1ModeEnum.HOT_WATER,
                      ):

            if self.feature_flag.ghc_active:
                raise DE1APIUnsupportedFeatureError(
                    f"DE1 does not permit {mode} unless GHC is not installed."
                )

            if cs != API_MachineStates.Idle:
                raise DE1APIUnsupportedStateTransitionError(mode, cs, css)

            if mode is DE1ModeEnum.ESPRESSO:
                logger.debug("API triggered _flow_start_espresso()")
                await self._flow_start_espresso()

            elif mode is DE1ModeEnum.HOT_WATER_RINSE:
                logger.debug("API triggered _flow_start_hot_water_rinse()")
                await self._flow_start_hot_water_rinse()

            elif mode is DE1ModeEnum.STEAM:
                logger.debug("API triggered _flow_start_steam()")
                await self._flow_start_steam()

            elif mode is DE1ModeEnum.HOT_WATER:
                logger.debug("API triggered _flow_start_hot_water()")
                await self._flow_start_hot_water()

        elif mode in (DE1ModeEnum.CLEAN,
                      DE1ModeEnum.DESCALE,
                      DE1ModeEnum.TRANSPORT,
                      ):
            if cs != API_MachineStates.Idle:
                raise DE1APIUnsupportedStateTransitionError(mode, cs, css)
            next_state = None
            if mode == DE1ModeEnum.CLEAN:
                next_state = API_MachineStates.Clean
            elif mode == DE1ModeEnum.DESCALE:
                next_state = API_MachineStates.Descale
            elif mode == DE1ModeEnum.TRANSPORT:
                next_state = API_MachineStates.AirPurge
            if next_state is None:
                raise DE1APIValueError(
                    f"Logic error in recognizing {mode.name}"
                )
            logger.debug(f"API triggered state change for {mode.name}")
            await self.write_packed_attr(RequestedState(State=next_state))

        elif mode is DE1ModeEnum.NO_REQUEST:
            logger.debug("API triggered NoRequest state change")
            await self.write_packed_attr(
                RequestedState(State=API_MachineStates.NoRequest))

        else:
            raise DE1APIUnsupportedStateTransitionError(mode, cs, css)

    @property
    def profile_id(self):
        if self._latest_profile is not None:
            return self._latest_profile.id
        else:
            return None

    async def set_profile_by_id(self, pid: str):

        async with aiosqlite.connect(config.database.FILENAME) as db:
            cur: aiosqlite.Cursor = await db.execute(
                'SELECT source, source_format FROM profile '
                'WHERE id == :id', (pid,)
            )
            row = await cur.fetchone()

        if row is None:
            raise DE1DBNoMatchingRecord(
                f"No profile record for {pid}")
        (source, source_format) = row
        if source_format != SourceFormat.JSONv2.value:
            raise DE1APITypeError(
                f"Only JSONv2 profiles supported, not {source_format}"
            )

        await self.upload_json_v2_profile(source)


    async def _sleep_if_bored(self):
        # TODO: Though an async task can be killed, be polite on shutdown
        RECHECK_TIME = 30 # seconds
        # NB: Internals are in seconds, auto_off_time is in minutes
        while True:
            if not self._auto_off_time \
                    or not self.state_last_updated \
                    or not self.is_ready:
                pass
            else:
                now = time.time()
                dt = now - self.state_last_updated
                if dt > self._auto_off_time \
                        and self.current_state != API_MachineStates.Sleep:
                    logger.info(
                        f"Sleeping with auto-off of {self._auto_off_time} sec")
                    await self.sleep()
            await asyncio.sleep(RECHECK_TIME)


class CalData:
    """
    Holder for the set of (normalized) data from the Calibration CUUID
    """

    # setters need to be consistent with create_Calibration_callback()

    def __init__(self):
        self._flow = None
        self._pressure = None
        self._temperature = None

    @property
    def flow(self):
        return self._flow

    def record_flow(self, de1_value: float, measured: float):
        # "record_" to be very clear it doesn't change the DE1
        if de1_value != 1:
            logger.error(
                f"Setting cal flow ratio expected 1, got {de1_value}")
        self._flow = measured / de1_value

    @property
    def pressure(self):
        return self._pressure

    def record_pressure(self, de1_value: float, measured: float):
        if de1_value != 1:
            logger.error(
                f"Setting cal press ratio expected 1, got {de1_value}")
        self._pressure = measured / de1_value

    @property
    def temperature(self):
        return self._pressure

    def record_temperature(self, de1_value: float, measured: float):
        if de1_value != 0:
            logger.error(
                f"Setting cal temp offset expected 0, got {de1_value}")
        self._temperature = measured - de1_value


class FeatureFlag:
    """
    Tests for DE1/firmware variants' capabilities
    True/False if known
    None if unknown (typically firmware version or CUUID not yet read)
    """

    def __init__(self, de1: DE1):
        self._de1 = de1

    def as_dict(self) -> dict:
        filtered = {}
        for name, value in inspect.getmembers(self):
            if not name.startswith('_') and name != 'as_dict':
                filtered[name] = value
        return filtered

    # Known, recent versions:
    # 1238  7252229 2021-02-02
    # 1246  b80dc98 2021-03-25
    # 1250  3bf4bc9 2021-03-30
    # 1255  a03eeec 2021-04-08
    #       48cc5e1 2021-05-04
    # 1260  2eae3cc 2021-05-06  Skip-to-next
    # 1265  224a312 2021-06-30
    # 1283  d8e169b 2021-09-30  Rinse (flush) control, Hot water flow (?)

    @property
    def fw_version(self):
        try:
            return self._de1._mmr_dict[
                MMR0x80LowAddr.CPU_FIRMWARE_BUILD].data_decoded
        except AttributeError:
            return None

    @property
    def ghc_active(self):
        try:
            ghc_info = self._de1._mmr_dict[
                MMR0x80LowAddr.GHC_INFO].data_decoded
        except AttributeError:
            ghc_info = None
        if ghc_info is None:
            return None
        elif ghc_info & MMRGHCInfoBitMask.GHC_ACTIVE:
            return True
        else:
            return False

    @property
    def last_mmr0x80(self):

        if self.fw_version < 1250:
            # CAL_FLOW_EST was probably in 1246, but be conservative
            logger.warning(
                f"Firmware {self.fw_version} is 'ancient', update suggested.")
            retval = MMR0x80LowAddr.HEATER_UP2_FLOW

        elif self.fw_version < 1283:
            retval = MMR0x80LowAddr.CAL_FLOW_EST

        else:
            retval = MMR0x80LowAddr.LAST_KNOWN

        return retval

    @property
    def safe_to_read_mmr_continuous(self):
        # FW 1260 and prior would freeze if an attempt was made to read
        # GHC_INFO or PREF_GHC_MCI
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1265

    # Fails on 1260 and prior
    # Readable on 1265, though returns 0 decoded as '<I'
    @property
    def mmr_pref_ghc_mci(self):
        if self.fw_version is None:
            return None
        else:
            return False

    # Untested, but assumed to fail on 1260
    # Readable on 1265, though returns 0 decoded as '<I'
    @property
    def max_shot_press(self):
        return self.mmr_pref_ghc_mci

    @property
    def skip_to_next(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1260

    @property
    def rinse_control(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1283

    @property
    def hot_water_flow_control(self):
        if self.fw_version is None:
            return None
        else:
            return False    # Seemingly not supported in 1283

