"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import time

from typing import Union

from pyDE1 import de1
from pyDE1.de1.c_api import Versions, RequestedState, SetTime, \
    ReadFromMMR, WriteToMMR, Temperatures, ShotSettings, \
    ShotSample, StateInfo, HeaderWrite, FrameWrite, \
    WaterLevels, FWMapRequest, \
    MMR0x80LowAddr

from pyDE1.de1.events import StateUpdate, ShotSampleUpdate, WaterLevelUpdate
from pyDE1.de1.c_api import API_MachineStates, API_Substates

from pyDE1.de1.ble import CUUID
from pyDE1.exceptions import DE1ErrorStateReported, MMRAddressOffsetError

from pyDE1.utils import data_as_readable_or_hex

# Logging is set to DEBUG by default. This effectively disables them
# with independent control. (The evaluation of the f-string is still done)
for cuuid in CUUID:
    logging.getLogger(
        f"{cuuid.__str__()}.Notify").setLevel(logging.INFO)

def default_handler_map(de1: de1):
    return {
        CUUID.Versions: create_Versions_callback(de1),
        CUUID.RequestedState: create_RequestedState_callback(de1),
        CUUID.SetTime: create_SetTime_callback(de1),
        CUUID.ShotDirectory: create_ShotDirectory_callback(de1),
        CUUID.ReadFromMMR: create_ReadFromMMR_callback(de1),
        CUUID.WriteToMMR: create_WriteToMMR_callback(de1),
        CUUID.ShotMapRequest: create_ShotMapRequest_callback(de1),
        CUUID.DeleteShotRange: create_DeleteShotRange_callback(de1),
        CUUID.FWMapRequest: create_FWMapRequest_callback(de1),
        CUUID.Temperatures: create_Temperatures_callback(de1),
        CUUID.ShotSettings: create_ShotSettings_callback(de1),
        CUUID.Deprecated: create_Deprecated_callback(de1),
        CUUID.ShotSample: create_ShotSample_callback(de1),
        CUUID.StateInfo: create_StateInfo_callback(de1),
        CUUID.HeaderWrite: create_HeaderWrite_callback(de1),
        CUUID.FrameWrite: create_FrameWrite_callback(de1),
        CUUID.WaterLevels: create_WaterLevels_callback(de1),
        CUUID.Calibration: create_Calibration_callback(de1),
    }

"""
bleak takes either standard functions or coroutines

        if inspect.iscoroutinefunction(callback):

            def bleak_callback(s, d):
                asyncio.ensure_future(callback(s, d))

        else:
            bleak_callback = callback


From the Python docs
    Important See also the create_task() function 
    which is the preferred way for creating new Tasks.
    

So it looks like a coroutine will be thrown on the loop

GO WITH THAT ASSUMPTION
"""

def create_Versions_callback(de1: de1):

    async def Versions_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = Versions().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.Versions].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.Versions.__str__()}.Notify")
        logger.debug(obj.log_string())
    return Versions_callback


def create_RequestedState_callback(de1: de1):

    async def RequestedState_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = RequestedState().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.RequestedState].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.RequestedState.__str__()}.Notify")
        logger.debug(obj.log_string())
    return RequestedState_callback


def create_SetTime_callback(de1: de1):

    async def SetTime_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = SetTime().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.SetTime].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.SetTime.__str__()}.Notify")
        logger.debug(obj.log_string())
    return SetTime_callback


def create_ShotDirectory_callback(de1: de1):

    async def ShotDirectory_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        # obj = ShotDirectory().from_wire_bytes(data, arrival_time)
        # logger.debug(obj.log_string())
        de1._cuuid_dict[CUUID.ShotDirectory].mark_updated(data, arrival_time)
        logger = logging.getLogger(f"{CUUID.ShotDirectory.__str__()}.Notify")
        logger.debug(f"{data_as_readable_or_hex(data)} ({len(data)})")
    return ShotDirectory_callback


def create_ReadFromMMR_callback(de1: de1):

    async def ReadFromMMR_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()

        # A read of CUUID.ReadFromMMR returns the request ReadFromMMR
        # not the "usual" data from the MMR that is "notified" here
        # For this case, Len means number of words - 1 for the request
        # It needs to be special-cased here
        # and probably doesn't need the read-on-write behavior

        # It's not obvious how to know this is reading back
        # from CUUID.ReadFromMMR as the request has the target address

        obj = ReadFromMMR().from_wire_bytes(data, arrival_time,
                                            from_response=True)
        # Logging of the full response is intentionally
        # early as MMR may contain multiple registers
        logger = logging.getLogger(f"{CUUID.ReadFromMMR.__str__()}.Notify")
        logger.debug(obj.log_string())
        if obj.addr_high != 0x80:
            # Can't write these to de1._mmr_dict as it assumes 0x80
            logger.error(
                "Unhandled MMR response from "
                f"0x{obj.addr_high:02x} {obj.addr_low:04x}"
            )

        elif obj.is_within_debug_log:
            # If completely within the debug-log region, take as a whole
            # Not being actively handled right now
            notify_state = de1._mmr_dict[obj.addr_low]
            notify_state.data_raw = obj.Data
            notify_state.mark_updated(obj, arrival_time)
            ds = data_as_readable_or_hex(notify_state.data_decoded,
                                         replace_rnt=True)
            logger.debug(f"Debug log: {ds}")

        elif (obj.Len % 4 != 0) or (obj.addr_low % 4 != 0):
            raise MMRAddressOffsetError(
                "Only MMR stride of 4 bytes is implemented at this time."
                f"len(mmr_bytes) bytes at 0x{obj.addr_low:04x} passed."
            )

        else:
            # Split into four-byte segments and process
            start = 0
            while (start + 4) <= obj.Len:
                this_addr = obj.addr_low + start
                notify_state = de1._mmr_dict[this_addr]
                notify_state.data_raw = obj.Data[start:(start + 4)]
                # This ensures that the data is decoded before Event.set()
                notify_state.mark_updated(notify_state.data_raw, arrival_time)
                try:
                    mmr = MMR0x80LowAddr(this_addr).__str__()
                except ValueError:
                    mmr = f"MMR0x80LowAddr.{this_addr:0x04x}"
                logging.getLogger(mmr).debug(notify_state.data_decoded)
                start += 4
        de1._cuuid_dict[CUUID.ReadFromMMR].mark_updated(obj, arrival_time)
    return ReadFromMMR_callback


def create_WriteToMMR_callback(de1: de1):

    async def WriteToMMR_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()

        # TODO: This needs to manage from_response as well
        #       Can they both be handled in MMRData?

        obj = WriteToMMR().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.WriteToMMR].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.WriteToMMR.__str__()}.Notify")
        logger.debug(obj.log_string())
    return WriteToMMR_callback


def create_ShotMapRequest_callback(de1:de1):

    async def ShotMapRequest_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        # obj = ShotMapRequest().from_wire_bytes(data, arrival_time)
        # logger.debug(obj.log_string())
        de1._cuuid_dict[CUUID.ShotMapRequest].mark_updated(data, arrival_time)
        logger = logging.getLogger(f"{CUUID.ShotMapRequest.__str__()}.Notify")
        logger.debug(f"{data_as_readable_or_hex(data)} ({len(data)})")
    return ShotMapRequest_callback


def create_DeleteShotRange_callback(de1: de1):

    async def DeleteShotRange_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        # obj = DeleteShotRange().from_wire_bytes(data, arrival_time)
        # logger.debug(obj.log_string())
        de1._cuuid_dict[CUUID.DeleteShotRange].mark_updated(data, arrival_time)
        logger = logging.getLogger(f"{CUUID.DeleteShotRange.__str__()}.Notify")
        logger.debug(f"{data_as_readable_or_hex(data)} ({len(data)})")
    return DeleteShotRange_callback


def create_FWMapRequest_callback(de1: de1):

    async def FWMapRequest_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = FWMapRequest().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.FWMapRequest].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.FWMapRequest.__str__()}.Notify")
        logger.debug(obj.log_string())
    return FWMapRequest_callback


def create_Temperatures_callback(de1: de1):

    async def Temperatures_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = Temperatures().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.Temperatures].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.Temperatures.__str__()}.Notify")
        logger.debug(obj.log_string())
    return Temperatures_callback


def create_ShotSettings_callback(de1: de1):

    async def ShotSettings_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = ShotSettings().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.ShotSettings].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.ShotSettings.__str__()}.Notify")
        logger.debug(obj.log_string())
    return ShotSettings_callback


def create_Deprecated_callback(de1: de1):

    async def Deprecated_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        # obj = Deprecated().from_wire_bytes(data, arrival_time)
        # logger.debug(obj.log_string())
        de1._cuuid_dict[CUUID.Deprecated].mark_updated(data, arrival_time)
        logger = logging.getLogger(f"{CUUID.Deprecated.__str__()}.Notify")
        logger.error(f"{data_as_readable_or_hex(data)} ({len(data)})")
    return Deprecated_callback


def create_ShotSample_callback(de1: de1):

    async def ShotSample_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = ShotSample().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.ShotSample].mark_updated(obj, arrival_time)
        await de1._event_shot_sample.publish(
            ShotSampleUpdate(
                arrival_time=arrival_time,
                sample_time=obj.SampleTime,
                group_pressure=obj.GroupPressure,
                group_flow=obj.GroupFlow,
                mix_temp=obj.MixTemp,
                head_temp=obj.HeadTemp,
                set_mix_temp=obj.SetMixTemp,
                set_head_temp=obj.SetHeadTemp,
                set_group_pressure=obj.SetGroupPressure,
                set_group_flow=obj.SetGroupFlow,
                frame_number=obj.FrameNumber,
                steam_temp=obj.SteamTemp,
            ))
        logger = logging.getLogger(f"{CUUID.ShotSample.__str__()}.Notify")
        logger.debug(obj.log_string())
    return ShotSample_callback


def create_StateInfo_callback(de1: de1):
    """
    NB: This can block itself.

    The working assumption is that a coroutine is thrown at the loop
    and that the "fairness" of the lock will keep things in order
    """

    previous_state = API_MachineStates.NoRequest
    previous_substate = API_Substates.NoState
    previous_lock = asyncio.Lock()

    async def StateInfo_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1, previous_state, previous_substate, previous_lock

        arrival_time = time.time()
        obj = StateInfo().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.StateInfo].mark_updated(obj, arrival_time)

        if obj.State == API_MachineStates.FatalError or obj.SubState.is_error:
            details = f"DE1 reported error condition: {obj.log_string()}"
            logger = logging.getLogger(f"{CUUID.StateInfo.__str__()}.Notify")
            logger.error(details)
            raise DE1ErrorStateReported(details)

        # Keep the DE1 up to date as quickly s possible
        de1._current_state = obj.State
        de1._current_substate = obj.SubState

        async with previous_lock:
            # Put the message onto the loop to be able to drop the lock faster
            await de1._event_state_update.publish(
                StateUpdate(
                    arrival_time=arrival_time,
                    state=obj.State,
                    substate=obj.SubState,
                    previous_state=previous_state,
                    previous_substate=previous_substate,
                ))
            previous_state = obj.State
            previous_substate = obj.SubState

        logger = logging.getLogger(f"{CUUID.StateInfo.__str__()}.Notify")
        logger.debug(obj.log_string())
    return StateInfo_callback


def create_HeaderWrite_callback(de1: de1):

    async def HeaderWrite_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = HeaderWrite().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.HeaderWrite].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.HeaderWrite.__str__()}.Notify")
        logger.debug(obj.log_string())
    return HeaderWrite_callback


def create_FrameWrite_callback(de1: de1):

    async def FrameWrite_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = FrameWrite().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.FrameWrite].mark_updated(obj, arrival_time)
        logger = logging.getLogger(f"{CUUID.FrameWrite.__str__()}.Notify")
        logger.debug(obj.log_string())
    return FrameWrite_callback


def create_WaterLevels_callback(de1: de1):

    async def WaterLevels_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        obj = WaterLevels().from_wire_bytes(data, arrival_time)
        de1._cuuid_dict[CUUID.WaterLevels].mark_updated(obj, arrival_time)
        await de1._event_water_levels.publish(
            WaterLevelUpdate(
                arrival_time=arrival_time,
                level=obj.Level,
                start_fill_level=obj.StartFillLevel,
            ))
        logger = logging.getLogger(f"{CUUID.WaterLevels.__str__()}.Notify")
        logger.debug(obj.log_string())
    return WaterLevels_callback


def create_Calibration_callback(de1:de1):

    async def Calibration_callback(sender: int, data: Union[bytes, bytearray]):
        nonlocal de1
        arrival_time = time.time()
        # obj = Calibration().from_wire_bytes(data, arrival_time)
        # logger.debug(obj.log_string())
        de1._cuuid_dict[CUUID.Calibration].mark_updated(data, arrival_time)
        logger = logging.getLogger(f"{CUUID.Calibration.__str__()}.Notify")
        logger.debug(f"{data_as_readable_or_hex(data)} ({len(data)})")
    return Calibration_callback


