"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

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
import requests
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

import pyDE1.database.insert as db_insert
import pyDE1.de1.handlers
from pyDE1.bledev.managed_bleak_device import ManagedBleakDevice
from pyDE1.config import config
from pyDE1.de1.ble import UnsupportedBLEActionError, CUUID
from pyDE1.de1.c_api import (
    PackedAttr, RequestedState, ReadFromMMR, WriteToMMR, StateInfo,
    FWMapRequest, FWErrorMapRequest, FWErrorMapResponse,
    API_MachineStates, API_Substates, MAX_FRAMES, get_cuuid, MMR0x80LowAddr,
    packed_attr_from_cuuid, pack_one_mmr0x80_write, MMRGHCInfoBitMask,
    CalCommand, CalTargets, Calibration, ShotSettings, AppFeatureFlag
)
from pyDE1.de1.events import ShotSampleUpdate, ShotSampleWithVolumesUpdate
from pyDE1.de1.firmware_file import FirmwareFile
from pyDE1.de1.notifications import NotificationState, MMR0x80Data
from pyDE1.de1.profile import (
    Profile, ProfileByFrames, DE1ProfileValidationError, SourceFormat
)
from pyDE1.dispatcher.resource import ConnectivityEnum, DE1ModeEnum
from pyDE1.event_manager.event_manager import SubscribedEvent
from pyDE1.event_manager.events import (
    FirmwareUploadState, FirmwareUpload, DeviceRole,
)
from pyDE1.exceptions import *
from pyDE1.flow_sequencer import FlowSequencer
from pyDE1.scanner import RegisteredPrefixes, find_first_matching

from pyDE1.singleton import Singleton
from pyDE1.utils import task_name_exists, cancel_tasks_by_name

import pyDE1.shutdown_manager as sm

RegisteredPrefixes.add_to_role('DE1', DeviceRole.DE1)


class DE1 (Singleton, ManagedBleakDevice):

    # NB: This is intentionally done in _singleton_init() and not __init__()
    #     See Singleton and Guido's notes there
    #
    #     No parameters are passed as there is no guarantee that any call
    #     will be "the first" call that is the one that initializes
    #
    # def __init__(self):
    #     pass

    def _singleton_init(self):

        self.logger = pyDE1.getLogger('DE1')
        self._role = DeviceRole.DE1
        self._name = ''
        ManagedBleakDevice.__init__(self)

        self._handlers = pyDE1.de1.handlers.default_handler_map(self)

        # TODO: These would benefit from accessor methods
        self._cuuid_dict: Dict[CUUID, NotificationState] = dict()
        self._mmr_dict: Dict[Union[MMR0x80LowAddr, int], MMR0x80Data] = dict()
        # Needs to be consistent with create_Calibration_callback()
        self._cal_factory = CalData()
        self._cal_local = CalData()

        self._latest_profile: Optional[Profile] = None

        self._feature_flag = FeatureFlag(self)

        self._event_state_update = SubscribedEvent(self)
        self._event_shot_sample = SubscribedEvent(self)
        self._event_water_levels = SubscribedEvent(self)
        self._event_shot_sample_with_volumes_update = SubscribedEvent(self)
        self._event_firmware_upload = SubscribedEvent(self)


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

        # Used for volume estimation at this time
        self._ssus_last_sample_time = 0
        self._ssus_start_up = True
        asyncio.create_task(
            self._event_shot_sample.subscribe(
                self._shot_sample_update_subscriber))

        self._sleep_watcher_task = asyncio.create_task(self._sleep_if_bored())
        self._sleep_watcher_task.add_done_callback(
            lambda s: (not sm.shutdown_underway
                       and self.logger.error(f"SIB: Task exited {s}")))
        self._sleep_watcher_task.set_name('SIB')

    def __del__(self):
        if self._sleep_watcher_task is not None:
            self._sleep_watcher_task.cancel()

    #
    # High-level initialization and re-initialization
    #

    def _prepare_for_connection(self):
        """
        Basically wipe all cached state
        """
        if self.is_connected:
            raise DE1IsConnectedError(
                "Can't prepare_for_connection() while connected.")

        self.logger.info(
            f"prepare_for_connection()")

        # This covers cases where DE1() is called before the loop is running
        loop = asyncio.get_running_loop()
        if loop is not None and loop.is_running():
            self._notify_not_ready()
        else:
            self.logger.debug(f"No running loop to _notify_not_ready(): {loop}")

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

    async def _initialize_after_connection(self, hold_ready=False):

        self.logger.info("initialize_after_connection()")

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

        self.logger.info(f"Waiting for {len(event_list)} responses")
        try:
            results = await asyncio.wait_for(asyncio.gather(*gather_list),
                             config.de1.MAX_WAIT_FOR_READY_EVENTS)
            t1 = time.time()
            self.logger.info(
                f"{len(event_list)} responses received in "
                f"{t1 - t0:.3f} seconds")
        except asyncio.TimeoutError:
            self.logger.warning("Timeout waiting for responses.")
            idx = 0
            for event in event_list:
                event: asyncio.Event
                if not event.is_set():
                    if idx < len(event_list) - 1:
                        addr_low = addr_low_list[idx]
                        failed = MMR0x80LowAddr.for_logging(addr_low,
                                                            return_as_hex=True)
                        self.logger.warning(
                            f"No response from #{idx + 1} "
                            f"of {len(event_list)}, "
                            f"{failed} (0x{addr_low:04x})"
                        )
                        # Retry
                        await self.read_one_mmr0x80(addr_low)
                    else:
                        self.logger.warning(
                            "No response from CUUID.StateInfo"
                        )
                        await self.read_cuuid(CUUID.StateInfo)
                idx += 1
            self.logger.error("Stupidly continuing anyway after re-requesting")

        # "By definition" this version understands UserNotPresent substate
        # it is de1app that is broken and the reason the toggle exists
        if self.feature_flag.app_feature_flag_user_present:
            await self.write_and_read_back_mmr0x80(
                MMR0x80LowAddr.APP_FEATURE_FLAGS, AppFeatureFlag.USER_PRESENT)

        # Although generally not needed "immediately", deferring to "ready"
        # can result in timeouts as ready can trigger multiple API requests
        await self.fetch_calibration()

        await FlowSequencer().on_de1_nearly_ready()

        self._notify_ready()

        # There's a Catch-22 here as the API needs is_ready
        # but then this becomes yet another competitor for cycles
        asyncio.get_running_loop().run_in_executor(None,
                                                   self._patch_on_connect)
        return


    def _patch_on_connect(self):
        poc = config.de1.PATCH_ON_CONNECT
        if isinstance(poc, dict) and len(poc.keys()):
            self.logger.info(f"Requesting PATCH_ON_CONNECT {poc}")
            host = config.http.SERVER_HOST
            if len(host) == 0:
                host = 'localhost'
            de1_url = "http://{}:{}{}de1".format(
                host,
                config.http.SERVER_PORT,
                config.http.SERVER_ROOT
            )
            self.logger.info(f"Making request to {de1_url}")
            # This ends up blocking as it doesn't release the thread
            req = requests.patch(
                url=de1_url,
                json=poc
            )
            if req.ok:
                level = logging.INFO
            else:
                level = logging.ERROR
            self.logger.log(level, "Response from PATCH_ON_CONNECT: "
                              f"{req.status_code} {req.reason} {req.content}")
        else:
            self.logger.info(f"PATCH_ON_CONNECT not a populated dict {poc}")

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

    #
    # Self-contained calls for API
    #

    async def change_de1_to_id(self, ble_device_id: Optional[str]):
        """
        For now, this won't return until connected or fails to connect
        As a result, will trigger the timeout on API calls
        """
        self.logger.info(f"Address change requested for DE1 from {self.address} "
                    f"to {ble_device_id}")

        if ble_device_id == 'scan':
            await self.connect_to_first_if_found()
        else:
            await self.change_address(ble_device_id)

        return self.address

    async def connect_to_first_if_found(self):
        if self.is_connected:
            self.logger.warning(
                "'scan' requested, but already connected. "
                "No action taken.")
        else:
            device = await find_first_matching(DeviceRole.DE1)
            if device:
                await self.change_address(device)
                await self.capture()
        return self.address

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

    async def disconnect(self):
        await self.release()

    #
    # With ManagedBleakDevice, move as much as possible into the
    # on_connectivity_change callback.
    #

    async def start_notifying(self, cuuid: CUUID) -> asyncio.Event:
        try:
            notified_event = self._cuuid_dict[cuuid].mark_requested()
            await self._bleak_client.start_notify(cuuid.uuid,
                                                  self._handlers[cuuid])
            pyDE1.getLogger(f"DE1.{cuuid.__str__()}").debug("Start notify")
        except KeyError:
            raise DE1NoHandlerError(f"No handler found for {cuuid}")
        return notified_event

    async def stop_notifying(self, cuuid: CUUID):
        try:
            self._cuuid_dict[cuuid].mark_ended()
            await self._bleak_client.stop_notify(cuuid.uuid)
            pyDE1.getLogger(f"DE1.{cuuid.__str__()}").debug("Stop notify")
        except KeyError:
            raise DE1NoHandlerError(f"No handler found for {cuuid}")

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
                "Timeout waiting for lock or request/notify. Aborting process.")
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
                                                          str]) -> dict:
        pbf = await self._process_json_v2_profile_inner(profile,
                                                        upload_to_de1=True)
        return {'id': pbf.id, 'fingerprint': pbf.fingerprint}

    async def store_json_v2_profile(self, profile: Union[bytes,
                                                         bytearray,
                                                         str]) -> dict:
        pbf = await self._process_json_v2_profile_inner(profile,
                                                        upload_to_de1=False)
        return {'id': pbf.id, 'fingerprint': pbf.fingerprint}

    async def _process_json_v2_profile_inner(
            self, profile: Union[bytes,
                           bytearray,
                           str], upload_to_de1=True) -> ProfileByFrames:

        pbf = ProfileByFrames().from_json(profile)
        if upload_to_de1:
            await self.upload_profile(pbf)
        else:
            self._fingerprint_profile_by_frames(pbf)
        async with aiosqlite.connect(config.database.FILENAME) as db:
            await db_insert.profile(pbf, db, time.time())
        return pbf

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
                self.logger.warning('Profile upload in progress being canceled')
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
            self.logger.info(f"Upload task exception: {upload_task.exception()}")
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

                # NB: Fingerprint code is replicated in
                #     _fingerprint_profile_by_frames()

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

                async with aiosqlite.connect(config.database.FILENAME) as db:
                    await db_insert.persist_last_profile(profile, db)
                self.logger.info(f"Selected profile ID: {profile.id}")

                if profile.number_of_preinfuse_frames is not None:
                    self._number_of_preinfuse_frames = \
                        profile.number_of_preinfuse_frames

                if profile.tank_temperature is not None \
                    and override_tank_temperature:
                    self.logger.info(
                        f"Setting tank temp to {profile.tank_temperature}")
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

                FlowSequencer().espresso_control.mow_all_frames \
                    = profile.move_on_weight_list
                if profile.move_on_weight_list is not None:
                    if not self.feature_flag.skip_to_next:
                        self.logger.warning(
                            "DE1 does not support skip to next as requested by "
                            f"profile {profile.title}: {profile.move_on_weight_list}"
                        )

                self._latest_profile = profile

        except asyncio.CancelledError:
            pass
        finally:
            profile_upload_stopped.set()

    def _fingerprint_profile_by_frames(self, profile: ProfileByFrames):

        # NB: Fingerprint code is replicated from
        #     _upload_profile()

        bytes_for_fingerprint = bytearray()

        # await self.write_packed_attr(profile.header_write())
        bytes_for_fingerprint += profile.header_write().as_wire_bytes()
        for frame in profile.shot_frame_writes():
            # await self.write_packed_attr(frame)
            bytes_for_fingerprint += frame.as_wire_bytes()
        for frame in profile.ext_shot_frame_writes():
            # await self.write_packed_attr(frame)
            bytes_for_fingerprint += frame.as_wire_bytes()
        # await self.write_packed_attr(profile.shot_tail_write())
        bytes_for_fingerprint \
            += profile.shot_tail_write().as_wire_bytes()

        profile._fingerprint = hashlib.sha1(
            bytes_for_fingerprint).hexdigest()



    async def write_and_read_back_mmr0x80(self, addr_low: MMR0x80LowAddr,
                                          value: Union[int, float, bool]):
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
            self.logger.info(f"About to wait for {addr_low.__repr__()}")
        await mmr_record.ready_event.wait()

        # old = mmr_record.data_decoded
        # value = (old + 0.1) % 20
        # self._logger.info(f"old and new t: {old} {value}")

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
                self.logger.warning('Firmware upload in progress being canceled')
                await self.cancel_firmware_upload()
            else:
                raise DE1OperationInProgressError
        t = asyncio.create_task(self._upload_firmware(fw),
                                name='upload_firmware')
        # t.add_done_callback()
        self.logger.info(f"Firmware upload started for {fw.filename}")
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
            self.logger.error(
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
        #     self._logger.debug(f"Report first: {fw_map_result.log_string()}")
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
        #         self._logger.debug(f"Report next: {fw_map_result.log_string()}")
        #         fix_addr = fw_map_result.FirstError
        #         if fix_addr == FWErrorMapResponse.NoneFound:
        #             break
        #
        # return retval

    @property
    def current_state(self) -> API_MachineStates:
        try:
            last_state = self._cuuid_dict[CUUID.StateInfo].last_value.State
        except KeyError:
            self.logger.warning("Current state requested before known")
            last_state = API_MachineStates.UNKNOWN
        return last_state

    @property
    def state_last_updated(self) -> Optional[float]:
        # Time in seconds
        try:
            last_updated = self._cuuid_dict[CUUID.StateInfo].last_updated
        except KeyError:
            last_updated = 0
        return last_updated

    @property
    def current_substate(self) -> API_Substates:
        return self._cuuid_dict[CUUID.StateInfo].last_value.SubState

    @property
    def current_frame(self) -> API_Substates:
        return self._cuuid_dict[CUUID.ShotSample].last_value.FrameNumber

    @property
    def frame_last_updated(self) -> float:
        try:
            last_updated = self._cuuid_dict[CUUID.ShotSample].last_updated
        except KeyError:
            last_updated = 0
        return last_updated

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

    async def _shot_sample_update_subscriber(self, ssu: ShotSampleUpdate):

        # Track volume dispensed

        # TODO: Reconstruct original DE1 clock prior to EventPayload

        # sample time is counts of half-cycles in a 16-bit unsigned int
        # Expect 25 if nothing is missed, 4 per second on 50 Hz, ~5 on 60
        if self._ssus_start_up:
            start_up = False
        else:
            t_inc = ssu.sample_time - self._ssus_last_sample_time
            if t_inc < 0:
                t_inc += 65536
            use_this = False
            if 24 < t_inc < 26:
                use_this = True
            elif 49 < t_inc < 51:
                use_this = True
                self.logger.warning(
                    f"Skipped update at {t_inc} samples? {ssu}"
                )
            else:
                use_this = False
                # Changed to warning (from error) here as seems to happen
                # around state change reports and heavy BLE traffic
                self.logger.warning(
                    f"Unexpected update period {t_inc} from {ssu}"
                )

            if use_this and self._tracking_volume_dispensed:
                v_inc = ssu.group_flow * t_inc / (self.line_frequency * 2)
                # since de1.volume_dispensed creates a copy,
                # and this should be the only "writer" other than clear
                # don't use a lock

                # TODO: Convince Ray to return substate and state
                #       in ShotSample so don't need to use frame count
                #       (also could help with the missed-Idle de1app bug)
                if ssu.frame_number > self._number_of_preinfuse_frames:
                    self._volume_dispensed_pour += v_inc
                else:
                    self._volume_dispensed_preinfuse += v_inc
                self._volume_dispensed_total += v_inc
                if self.current_state is API_MachineStates.Espresso:
                    to_frame = ssu.frame_number
                else:
                    to_frame = 0
                self._volume_dispensed_by_frame[to_frame] += v_inc

        self._ssus_last_sample_time = ssu.sample_time

        await self._event_shot_sample_with_volumes_update.publish(
            ShotSampleWithVolumesUpdate(
                ssu,
                volume_preinfuse=self._volume_dispensed_preinfuse,
                volume_pour=self._volume_dispensed_pour,
                volume_total=self._volume_dispensed_total,
                volume_by_frame=self._volume_dispensed_by_frame,
            )
        )

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
        """
        if self.feature_flag.skip_to_next:
            if self.current_state == API_MachineStates.Espresso:
                await self._request_state(API_MachineStates.SkipToNext)
                self.logger.info(
                    f"Skip to next request made from frame {self.current_frame}")
            else:
                self.logger.warning(
                    "Skip to next request ignored while in "
                    f"{self.current_state.name}")
        else:
            self.logger.warning("Skip to next not supported, request ignored.")

    async def stop_flow(self):
        """
        If in a flow state, request stopping flow
        Replaces legacy "go to Idle"
        """
        # TODO Can the logic around "already asked, wait a bit" be cleaned up?
        self.logger.info("stop_flow() called")
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
        self.logger.info("end_steam() called")
        log_level = None
        cs = self.current_state
        css = self.current_substate
        if cs is API_MachineStates.Steam:
                if css in (API_Substates.Pour,):
                    # Steaming, maybe
                    # PausedSteam and SteamPuff, probably not
                    current_shot_settings: ShotSettings = self._cuuid_dict[
                        CUUID.ShotSettings].last_value
                    temp_shot_settings: ShotSettings = deepcopy(
                        current_shot_settings)
                    temp_shot_settings.TargetSteamLength = 0
                    await self.write_packed_attr(temp_shot_settings)
                    self.logger.debug("Wrote zero-time to steam length")
                    await self.write_packed_attr(current_shot_settings)
                    tsl = current_shot_settings.TargetSteamLength
                    self.logger.debug(f"Restored {tsl} to steam length")
                else:
                    log_level = logging.WARNING
        else:
            log_level = logging.ERROR

        if log_level is not None:
            self.logger.log(
                log_level,
                f"end_steam() called during {cs},{css}, no action taken")


    async def idle(self):
        """
        This is an explicit request for Idle.

        de1.stop_flow() is probably more appropriate in many cases
        """
        self.logger.info("idle() called")
        await self._request_state(API_MachineStates.Idle)

    async def sleep(self):
        self.logger.info("sleep() called")
        if self.current_state not in (API_MachineStates.Idle,
                                      API_MachineStates.GoingToSleep,
                                      API_MachineStates.Refill):
            self.logger.warning(
                "Sleep requested while in {}, {}. Calling idle() first.".format(
                    self.current_state.name, self.current_substate.name
                ))
            await self.idle()
            # TODO: Really should wait here until Idle seen
            #       If so, how to deal with it if it doesn't idle soon?
        await self._request_state(API_MachineStates.Sleep)

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
            'last_updated': self.state_last_updated,
        }

    @property
    def state_update_last_sent(self):
        return self._event_state_update.last_sent.as_json()

    async def mode_setter(self, mode: DE1ModeEnum):
        assert isinstance(mode, DE1ModeEnum), \
            f"mode of {mode} not a DE1ModeEnum in DE1.mode_setter()"

        # Ensure GHC data has been read
        if self._mmr_dict[MMR0x80LowAddr.GHC_INFO].data_decoded is None:
            self.logger.info("GHC_INFO not present, reading now.")
            await self.read_one_mmr0x80_and_wait(MMR0x80LowAddr.GHC_INFO)

        cs = self.current_state
        if cs == API_MachineStates.NoRequest:
            self.logger.warning(f"Refreshing current state as is NoRequest")
            await self.read_cuuid(CUUID.StateInfo)
            cs = self.current_state
        css = self.current_substate
        self.logger.debug(f"Request to change mode to {mode} "
                     f"while in {API_MachineStates(cs).name}")

        if mode is DE1ModeEnum.SLEEP:
            self.logger.debug(f"current state: {cs}, {type(cs)}")
            if cs in (API_MachineStates.Idle,
                      API_MachineStates.Refill):
                self.logger.debug("API triggered sleep()")
                await self.sleep()
            elif self.current_state in (API_MachineStates.Sleep,
                                        API_MachineStates.GoingToSleep):
                pass
            else:
                raise DE1APIUnsupportedStateTransitionError(mode, cs, css)

        elif mode is DE1ModeEnum.WAKE:
            if cs in (API_MachineStates.Sleep,
                      API_MachineStates.GoingToSleep):
                self.logger.debug("API triggered idle()")
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
                self.logger.debug("API triggered idle()")
                await self.idle()
            if override_checks:
                self.logger.warning(
                    "API_STOP_IGNORES_CHECKS triggered idle() during "
                    f"{cs},{css}")
                await self.idle()

        elif mode is DE1ModeEnum.SKIP_TO_NEXT:
            if cs == API_MachineStates.Espresso \
                and self.current_substate in (API_Substates.PreInfuse,
                                              API_Substates.Pour):
                self.logger.debug("API triggered skip_to_next()")
                await self.skip_to_next()
            else:
                raise DE1APIUnsupportedStateTransitionError(mode, cs, css)

        elif mode is DE1ModeEnum.END_STEAM:
            if cs == API_MachineStates.Steam:
                if self.current_substate in (API_Substates.Pour,):
                    self.logger.debug("API triggered end_steam() for END_STEAM")
                    await self.end_steam()
                else:
                    self.logger.debug("API triggered stop_flow() for END_STEAM")
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
                self.logger.debug("API triggered _flow_start_espresso()")
                await self._flow_start_espresso()

            elif mode is DE1ModeEnum.HOT_WATER_RINSE:
                self.logger.debug("API triggered _flow_start_hot_water_rinse()")
                await self._flow_start_hot_water_rinse()

            elif mode is DE1ModeEnum.STEAM:
                self.logger.debug("API triggered _flow_start_steam()")
                await self._flow_start_steam()

            elif mode is DE1ModeEnum.HOT_WATER:
                self.logger.debug("API triggered _flow_start_hot_water()")
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
            self.logger.debug(f"API triggered state change for {mode.name}")
            await self.write_packed_attr(RequestedState(State=next_state))

        elif mode is DE1ModeEnum.NO_REQUEST:
            self.logger.debug("API triggered NoRequest state change")
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
        RECHECK_TIME = 60 # seconds
        # NB: Internals are in seconds, auto_off_time is in minutes
        while True:
            # Wait at top as never time to sleep when starting up
            # and avoids checking before CUUIDs are populated
            await asyncio.sleep(RECHECK_TIME)

            if not (self._auto_off_time
                    and self.state_last_updated
                    and self.is_ready):
                pass
            else:
                now = time.time()
                dt = now - self.state_last_updated
                if (dt > self._auto_off_time
                        and self.current_state != API_MachineStates.Sleep):
                    await self.sleep()


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
            self._logger.error(
                f"Setting cal flow ratio expected 1, got {de1_value}")
        self._flow = measured / de1_value

    @property
    def pressure(self):
        return self._pressure

    def record_pressure(self, de1_value: float, measured: float):
        if de1_value != 1:
            self._logger.error(
                f"Setting cal press ratio expected 1, got {de1_value}")
        self._pressure = measured / de1_value

    @property
    def temperature(self):
        return self._pressure

    def record_temperature(self, de1_value: float, measured: float):
        if de1_value != 0:
            self._logger.error(
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
    #       48cc5e1 2021-05-04  reverts to the old hot-water start behaviour
    # 1260  2eae3cc 2021-05-06  Skip-to-next
    # 1265  224a312 2021-06-30
    # 1283  d8e169b 2021-09-30  Rinse (flush) control, Hot water flow (?)
    #                               Reverted in commit 1b92cc41
    #                               (Has start-up temperature issues)
    # 1293  d014017 2021-12-22  "fixes problem with scheduler"

    # These are taken as a sequence and not "recognized" until 1320 or later
    # 1315  978d0efc 2022-05-31
    # 1316  5365f3e1 2022-06-01
    # 1317  36ad337f 2022-06-14
    # 1318  67b7de1b 2022-06-15 new way to indicate "user is present" to the DE1
    # 1320  f84a1b59 2022-07-10
    #   the steam problem caused by very low "limiter" values
    #       (such as "Filter 2.1") should now be fixed
    #   fast switching to Steam, if you press the GHC STEAM button
    #       as espresso is ending. The "ending" is cut off and steam starts faster.
    #   Auto-detection of the refill kit should be more reliable,
    #       so that you shouldn't need to set "refill-kit: on" in settings,
    #       ie, leave this on "auto-detect:
    # 1324  ac30fc78 2022-08-27 USB power restores 10 min after turning it off
    # 1325  1ae30ed7 2022-08-29 non-debug version of 1324
    # 1328  9eb07c2d 2022-10-08 fixes GHC tap-tap for small changes
    # 1330  0a9fd542 2022-10-27 fixes bugs with "auto detect refill kit" settings
    # 1333  360f4def 2022-11-14 "firmware v1333"

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
            self._logger.warning(
                f"Firmware {self.fw_version} is 'ancient', update suggested.")
            retval = MMR0x80LowAddr.HEATER_UP2_TIMEOUT

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
    def mmr_max_shot_press(self):
        if self.fw_version is None:
            return None
        else:
            return False

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

    @property
    def sched_idle(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1293

    @property
    def steam_purge_mode(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1320

    @property
    def allow_usb_charging(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1320

    @property
    def app_feature_flag_user_present(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1320

    @property
    def refill_kit_present(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1320

    @property
    def user_present(self):
        if self.fw_version is None:
            return None
        else:
            return self.fw_version >= 1320
