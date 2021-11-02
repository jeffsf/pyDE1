"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

# NB: can_read, can_write imply that *some* firmware versions support them.
#     Checks with feature_flag are important, especially for earlier firmware.

import asyncio
import copy
import enum
import time
import traceback
from struct import unpack, pack
from typing import Union, Optional

import pyDE1
from pyDE1.de1.ble import CUUID
from pyDE1.exceptions import (
    DE1APITypeError, DE1APIValueError, DE1APITooManyFramesError,
    MMRTypeError, MMRValueError, MMRDataTooLongError
)
from pyDE1.utils import data_as_hex

logger = pyDE1.getLogger('DE1.C_API')

# TODO: log_string() is not "None-safe"
#       TypeError: unsupported format string passed to NoneType.__format__


#
# Utilities for range check of APi types
#

def validate_f8_1_7(value):
    """
    Range check of F8_1_7 data type which is
    an unsigned, 7-bit mantissa
    with an exponent of either 0.1 or 1
    """
    if value < 0 or value > 127.5:
        raise DE1APIValueError("Out of range for F8_1_7 data type")
    return value


def validate_f8_1_7_noneok(value):
    if value is None:
        return None
    return validate_f8_1_7(value)


def f8_1_7_decode(value):
    mantissa = value & 0x7f
    if (value & 0x80):
        exponent = 1
    else:
        exponent = 0.1
    return mantissa * exponent


def f8_1_7(value):
    if value < 0:
        raise DE1APIValueError("Out of range for F8_1_7 data type")
    elif value < 12.75:
        retval = int(round(value * 10))
    elif value < 127.5:
        retval = int(round(value)) + 0x80
    else:
        raise DE1APIValueError("Out of range for F8_1_7 data type")
    return retval


def validate_s_p(value, s, p):
    scaled = round(value / 2**p)
    maxabs = 2**(s - 1)
    if scaled < -maxabs or scaled > (maxabs - 1):
        raise DE1APIValueError(f"Out of range for S{s}P{p} data type")
    return value

def validate_s_p_noneok(value, s, p):
    if value is None:
        return None
    return validate_s_p(value, s, p)


def validate_u_p(value, u, p):
    scaled = round(value / 2**p)
    if scaled < 0 or scaled > (2**u - 1):
        raise DE1APIValueError(f"Out of range for U{u}P{p} data type")
    return value


def validate_u_p_noneok(value, u, p):
    if value is None:
        return None
    return validate_u_p(value, u, p)

def u(val):
    return int(round(val))

def p0(val):
    return int(round(val))

def p1(val):
    return int(round(val * 2))

def p4(val):
    return int(round(val * 16))

def p8(val):
    return int(round(val * 256))

def p12(val):
    return int(round(val * 4096))

def p16(val):
    return int(round(val * 65536))


class PackedAttr:
    """
    Abstract parent of classes used represent struct PACKEDATTR
    from APIDataTypes.hpp (code running on the DE1)

    All should be able to support serialization and deserialization
    as well as providing a "log-safe" representation string.

    Range checking is generally done in subclasses. Can raise:
    DE1APITypeError and DE1APIValueError and subclasses
    """

    def __init__(self):
        self._arrival_time = None
        pass

    def from_wire_bytes(self, wire_bytes: Union[bytes, bytearray], arrival_time=None):
        self._arrival_time = arrival_time

        return self

    def as_wire_bytes(self) -> Union[bytes, bytearray]:
        raise NotImplementedError

    def log_string(self):
        return self.__repr__()

    @property
    def arrival_time(self):
        return self._arrival_time

    # Boilerplate here (could all be False for base class with cuuid = None)
    cuuid = None
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)



def get_cuuid(packed_attr: PackedAttr) -> CUUID:
    """
    :Protecting" getter -- raises if None
    """
    if (cuuid := packed_attr.cuuid) is None:
        raise DE1APIValueError(
            f"Not an over-the-wire PackedAttr {packed_attr}"
        )
    return cuuid



# def packed_attr_from_cuuid(cuuid: CUUID) -> PackedAttr:
# found at the end, as derived at load time from list of subclasses


#
# Follow the order in APUDataTypes.hpp for ease of maintenance
#


# Present, but apparently unused
class Models (enum.IntEnum):
    Model_Plus    = 1
    Model_Pro     = 2
    Model_CAFE    = 4


# Present, but apparently unused
class Config (enum.IntFlag):
    LowPowerHeater  = 0x1
    CFG_Refill      = 0x2
    Voltage_120V    = 0x4


class FWVersion (PackedAttr):

    def __init__(self, APIVersion=None, Release=None, Commits=None,
                 Changes=None, BLESha=None):
        super(FWVersion, self).__init__( )
        self.APIVersion = APIVersion
        self.Release = Release
        self.Commits = Commits
        self.Changes = Changes
        self.BLESha = BLESha

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(FWVersion, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            self._APIVersion,
            self._Release,  # F8_1_7
            self._Commits,
            self._Changes,
            self._BLESha,  # TODO: Interpret as 7 nibbles + dirty
         ) = unpack('>BBHBL', wire_bytes)
        self._Release = f8_1_7_decode(self._Release)

        return self

    def as_wire_bytes(self):
        return pack('>BBHBL',
                    p0(self._APIVersion),
                    f8_1_7(self._Release),
                    p0(self._Commits),
                    p0(self._Changes),
                    p0(self._BLESha),
                    )

    def log_string(self):
        return 'API: {} Release: {:.2f} Commits: {} Changes: {} SHA: {:07x}({})'.format(
            self._APIVersion,
            self._Release,
            self._Commits,
            self._Changes,
            self._BLESha >> 4,
            self._BLESha & 0x0f
        )

    @property
    def APIVersion(self):
        return self._APIVersion

    @APIVersion.setter
    def APIVersion(self, value):
        self._APIVersion = validate_u_p_noneok(value, 8, 0)

    @property
    def Release(self):
        return self._Release

    @Release.setter
    def Release(self, value):
        self._Release = validate_f8_1_7_noneok(value)

    @property
    def Commits(self):
        return self._Commits

    @Commits.setter
    def Commits(self, value):
        self._Commits = validate_u_p_noneok(value, 16, 0)

    @property
    def Changes(self):
        return self._Changes

    @Changes.setter
    def Changes(self, value):
        self._Changes = validate_u_p_noneok(value, 8, 0)

    @property
    def BLESha(self):
        return self._BLESha

    @BLESha.setter
    def BLESha(self, value):
        self._BLESha = validate_u_p_noneok(value, 32, 0)

    def BLESha_is_dirty(self):
        return (self._BLESha & 0b1 == 0b1)


class Versions (PackedAttr):

    cuuid = CUUID.Versions
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, BLEVersion=None, LVVersion=None):
        super(Versions, self).__init__()

        self.BLEVersion = BLEVersion
        self.LVVersion = LVVersion


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(Versions, self).from_wire_bytes(wire_bytes, arrival_time)
        self._BLEVersion.from_wire_bytes(wire_bytes[0:9], arrival_time)
        self._LVVersion.from_wire_bytes(wire_bytes[9:], arrival_time)

        return self

    def as_wire_bytes(self):
        retval = bytearray(self._BLEVersion.as_wire_bytes())
        retval.extend(self._LVVersion.as_wire_bytes())
        return retval

    def log_string(self):
        return 'BLE: {} LV: {}'.format(
            self._BLEVersion.log_string(),
            self._LVVersion.log_string(),
        )

    @property
    def BLEVersion(self):
        return copy.deepcopy(self._BLEVersion)

    @BLEVersion.setter
    def BLEVersion(self, obj):
        if not (isinstance(obj, FWVersion) or obj is None):
            raise DE1APITypeError("Expecting FWVersion")
        if obj is None:
            obj = FWVersion()
        self._BLEVersion = obj

    @property
    def LVVersion(self):
        return copy.deepcopy(self._LVVersion)

    @LVVersion.setter
    def LVVersion(self, obj):
        if not (isinstance(obj, FWVersion) or obj is None):
            raise DE1APITypeError("Expecting FWVersion")
        if obj is None:
            obj = FWVersion()
        self._LVVersion = obj


# Present, but apparently unused
class BoardVersion (enum.IntEnum):
    PRE_H   = 0
    H       = 1


class TemperatureSet (PackedAttr):

    def __init__(self, WaterHeater=None, SteamHeater=None,
                 GroupHeater=None, ColdWater=None):
        super(TemperatureSet, self).__init__()
        self.WaterHeater = WaterHeater
        self.SteamHeater = SteamHeater
        self.GroupHeater = GroupHeater
        self.ColdWater = ColdWater

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(TemperatureSet, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            self._WaterHeater,
            self._SteamHeater,
            self._GroupHeater,
            self._ColdWater
         ) = unpack(">HHHH", wire_bytes)

        self._WaterHeater = self._WaterHeater / 2**8
        self._SteamHeater = self._SteamHeater / 2**8
        self._GroupHeater = self._GroupHeater / 2**8
        self._ColdWater = self._ColdWater / 2**8

        return self

    def as_wire_bytes(self):
        raise NotImplementedError

    def log_string(self):
        return 'Water: {:.2f} Steam: {:.2f} Group: {:.2f} Cold: {:.2f}'.format(
            self._WaterHeater,
            self._SteamHeater,
            self._GroupHeater,
            self._ColdWater,
        )

    @property
    def WaterHeater(self):
        return self._WaterHeater

    @WaterHeater.setter
    def WaterHeater(self, value):
        self._WaterHeater = validate_u_p_noneok(value, 16, 8)

    @property
    def SteamHeater(self):
        return self._SteamHeater

    @SteamHeater.setter
    def SteamHeater(self, value):
        self._SteamHeater = validate_u_p_noneok(value, 16, 8)

    @property
    def GroupHeater(self):
        return self._GroupHeater

    @GroupHeater.setter
    def GroupHeater(self, value):
        self._GroupHeater = validate_u_p_noneok(value, 16, 8)

    @property
    def ColdWater(self):
        return self._ColdWater

    @ColdWater.setter
    def ColdWater(self, value):
        self._ColdWater = validate_u_p_noneok(value, 16, 8)


class Temperatures (PackedAttr):

    cuuid = CUUID.Temperatures
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, Current=None, Target=None):
        super(Temperatures, self).__init__()

        self.Current = Current
        self.Target = Target


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(Temperatures, self).from_wire_bytes(wire_bytes, arrival_time)
        self._Current.from_wire_bytes(wire_bytes[0:8], arrival_time)
        self._Target.from_wire_bytes(wire_bytes[8:], arrival_time)

        return self

    def as_wire_bytes(self):
        raise NotImplementedError

    def log_string(self):
        return 'Current: {} Target: {}'.format(
            self._Current.log_string(),
            self._Target.log_string(),
        )

    @property
    def Current(self):
        return copy.deepcopy(self._Current)

    @Current.setter
    def Current(self, obj):
        if not (isinstance(obj, TemperatureSet) or obj is None):
            raise DE1APITypeError("Expecting TemperatureSet")
        if obj is None:
            obj = TemperatureSet()
        self._Current = obj

    @property
    def Target(self):
        return copy.deepcopy(self._Target)

    @Target.setter
    def Target(self, obj):
        if not (isinstance(obj, TemperatureSet) or obj is None):
            raise DE1APITypeError("Expecting TemperatureSet")
        if obj is None:
            obj = TemperatureSet()
        self._Target = obj


class SteamSetting (enum.IntFlag):
    NoneSet   = 0x00  # Otherwise returns SlowStart
    FastStart = 0x80
    SlowStart = 0x00
    HighPower = 0x40
    LowPower  = 0x00


class ShotSettings (PackedAttr):

    cuuid = CUUID.ShotSettings
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, SteamSettings=None,
                 TargetSteamTemp=None, TargetSteamLength=None,
                 TargetHotWaterTemp=None, TargetHotWaterVol=None,
                 TargetHotWaterLength=None, TargetEspressoVol=None,
                 TargetGroupTemp=None
                 ):
        super(ShotSettings, self).__init__()

        self.SteamSettings = SteamSettings
        self.TargetSteamTemp = TargetSteamTemp
        self.TargetSteamLength = TargetSteamLength
        self.TargetHotWaterTemp = TargetHotWaterTemp
        self.TargetHotWaterVol = TargetHotWaterVol
        self.TargetSteamLength = TargetHotWaterLength
        self.TargetEspressoVol = TargetEspressoVol
        self.TargetGroupTemp = TargetGroupTemp


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotSettings, self).from_wire_bytes(wire_bytes, arrival_time)
        (self._SteamSettings,
        self._TargetSteamTemp,
        self._TargetSteamLength,
        self._TargetHotWaterTemp,
        self._TargetHotWaterVol,
        self._TargetHotWaterLength,
        self._TargetEspressoVol,
        self._TargetGroupTemp,
         ) = unpack('>BBBBBBBH', wire_bytes)

        self._TargetGroupTemp = self._TargetGroupTemp / 2**8

        return self

    def as_wire_bytes(self):
        return pack('>BBBBBBBH',
            p0(self._SteamSettings),
            p0(self._TargetSteamTemp),
            p0(self._TargetSteamLength),
            p0(self._TargetHotWaterTemp),
            p0(self._TargetHotWaterVol),
            p0(self._TargetHotWaterLength),
            p0(self._TargetEspressoVol),
            p8(self._TargetGroupTemp),
        )

    def log_string(self):
        if self._SteamSettings & SteamSetting.FastStart.value:
            steam_settings = "Fast"
        else:
            steam_settings = "Slow"
        if self._SteamSettings & SteamSetting.HighPower.value:
            steam_settings += ",High"
        else:
            steam_settings += ",Low"
        return 'Steam: {} Temp: {} Length: {}; ' \
            'Water: Temp: {} Vol: {} Length: {}; ' \
            'EVol: {} GTemp: {}'.format(
            steam_settings,
            self._TargetSteamTemp,
            self._TargetSteamLength,
            self._TargetHotWaterTemp,
            self._TargetHotWaterVol,
            self._TargetHotWaterLength,
            self._TargetEspressoVol,
            self._TargetGroupTemp,
        )

    @property
    def SteamSettings(self):
        return SteamSetting(self._SteamSettings)

    @SteamSettings.setter
    def SteamSettings(self, value):
        self._SteamSettings = validate_u_p_noneok(value, 8, 0)

    @property
    def steam_setting_fast_start(self):
        return bool(self.SteamSettings & SteamSetting.FastStart)

    @steam_setting_fast_start.setter
    def steam_setting_fast_start(self, val: bool):
        if val:
            self.SteamSettings = self.SteamSettings | SteamSetting.FastStart
        else:
            self.SteamSettings = self.SteamSettings & ~ SteamSetting.FastStart

    @property
    def steam_setting_high_power(self):
        return bool(self.SteamSettings & SteamSetting.FastStart)

    @steam_setting_high_power.setter
    def steam_setting_high_power(self, val: bool):
        if val:
            self.SteamSettings = self.SteamSettings | SteamSetting.HighPower
        else:
            self.SteamSettings = self.SteamSettings ^ SteamSetting.HighPower

    @property
    def TargetSteamTemp(self):
        return self._TargetSteamTemp

    @TargetSteamTemp.setter
    def TargetSteamTemp(self, value):
        if value is not None and (value < 140 or 160 < value) :
            raise DE1APIValueError("TargetSteamTemp must be 140 - 160")
        self._TargetSteamTemp = validate_u_p_noneok(value, 8, 0)

    @property
    def TargetSteamLength(self):
        return self._TargetSteamLength

    @TargetSteamLength.setter
    def TargetSteamLength(self, value):
        self._TargetSteamLength = validate_u_p_noneok(value, 8, 0)

    @property
    def TargetHotWaterTemp(self):
        return self._TargetHotWaterTemp

    @TargetHotWaterTemp.setter
    def TargetHotWaterTemp(self, value):
        self._TargetHotWaterTemp = validate_u_p_noneok(value, 8, 0)

    @property
    def TargetHotWaterVol(self):
        return self._TargetHotWaterVol

    @TargetHotWaterVol.setter
    def TargetHotWaterVol(self, value):
        self._TargetHotWaterVol = validate_u_p_noneok(value, 8, 0)

    @property
    def TargetHotWaterLength(self):
        return self._TargetHotWaterLength

    @TargetHotWaterLength.setter
    def TargetHotWaterLength(self, value):
        self._TargetHotWaterLength = validate_u_p_noneok(value, 8, 0)

    @property
    def TargetEspressoVol(self):
        return self._TargetEspressoVol

    @TargetEspressoVol.setter
    def TargetEspressoVol(self, value):
        self._TargetEspressoVol = validate_u_p_noneok(value, 8, 0)

    @property
    def TargetGroupTemp(self):
        return self._TargetGroupTemp

    @TargetGroupTemp.setter
    def TargetGroupTemp(self, value):
        self._TargetGroupTemp = validate_u_p_noneok(value, 16, 8)


class API_MachineStates (enum.IntEnum):
    Sleep           = 0x00
    GoingToSleep    = 0x01
    Idle            = 0x02
    Busy            = 0x03
    Espresso        = 0x04
    Steam           = 0x05
    HotWater        = 0x06
    ShortCal        = 0x07
    SelfTest        = 0x08
    LongCal         = 0x09
    Descale         = 0x0a
    FatalError      = 0x0b
    Init            = 0x0c
    NoRequest       = 0x0d  # Allows RequestedState to be sent as a noop
    SkipToNext      = 0x0e
    HotWaterRinse   = 0x0f
    SteamRinse      = 0x10
    Refill          = 0x11
    Clean           = 0x12
    InBootLoader    = 0x13
    AirPurge        = 0x14
    SchedIdle       = 0x15

    @property
    def is_flow_state(self):
        return self in (
            self.Espresso,
            self.Steam,
            self.HotWater,
            self.HotWaterRinse
        )


class API_Substates (enum.IntEnum):
    NoState             = 0x00
    HeatWaterTank       = 0x01
    HeatWaterHeater     = 0x02
    StabilizeMixTemp    = 0x03
    PreInfuse           = 0x04
    Pour                = 0x05
    Flush               = 0x06
    Steaming            = 0x07
    DescaleInit         = 0x08
    DescaleFillGroup    = 0x09
    DescaleReturn       = 0x0a
    DescaleGroup        = 0x0b
    DescaleSteam        = 0x0c
    CleanInit           = 0x0d
    CleanFillGroup      = 0x0e
    CleanSoak           = 0x0f
    CleanGroup          = 0x10
    PausedRefill        = 0x11
    PausedSteam         = 0x12

    Error_NaN           = 200
    Error_Inf           = 201
    Error_Generic       = 202
    Error_ACC           = 203
    Error_TSensor       = 204
    Error_PSensor       = 205
    Error_WLevel        = 206
    Error_DIP           = 207
    Error_Assertion     = 208
    Error_Unsafe        = 209
    Error_InvalidParm   = 210
    Error_Flash         = 211
    Error_OOM           = 212
    Error_Deadline      = 213
    Error_HiCurrent     = 214
    Error_LoCurrent     = 215
    Error_BootFill      = 216

    @property
    def is_error(self):
        return self.value >= 200

    @property
    def flow_phase(self):
        if self in (
            self.HeatWaterTank,
            self.HeatWaterHeater,
            self.StabilizeMixTemp
        ):
            retval = 'before'
        elif self in (
            self.PreInfuse,
            self.Pour,
            self.Steaming,
            self.PausedSteam
        ):
            retval = 'during'
        elif self in (
            self.Flush,
        ):
            retval = 'after'
        else:
            retval = None
        return retval

class StateInfo (PackedAttr):

    cuuid = CUUID.StateInfo
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, State=None, SubState=None):
        super(StateInfo, self).__init__()

        self.State = State
        self.SubState = SubState


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(StateInfo, self).from_wire_bytes(wire_bytes, arrival_time)
        # Even though "trivial", use of unpack checks against format
        ( state, substate ) = unpack('>BB', wire_bytes)
        self._State = API_MachineStates(state)
        self._SubState = API_Substates(substate)

        return self

    def as_wire_bytes(self):
        raise NotImplementedError

    def log_string(self):
        return '{},{}'.format(
            self._State.name,
            self._SubState.name,
        )

    @property
    def State(self):
        return self._State

    @State.setter
    def State(self, value):
        if not (isinstance(value, API_MachineStates) or value is None):
            raise DE1APITypeError("Expecting API_MachineStates")
        self._State = value

    @property
    def SubState(self):
        return self._SubState

    @SubState.setter
    def SubState(self, value):
        if not (isinstance(value, API_Substates) or value is None):
            raise DE1APITypeError("Expecting API_Substates")
        self._SubState = value


class RequestedState (PackedAttr):

    cuuid = CUUID.RequestedState
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    # NB: struct member is RequestedState
    def __init__(self, State=None):
        super(RequestedState, self).__init__()

        self.RequestedState = State


    def as_wire_bytes(self):
        return pack('>B', u(self._RequestedState.value))

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(RequestedState, self).from_wire_bytes(wire_bytes, arrival_time)
        state = unpack('>B', wire_bytes)[0]
        self._RequestedState = API_MachineStates(state)

        return self

    def log_string(self):
        return self._RequestedState.name

    @property
    def RequestedState(self):
        return self._RequestedState

    @RequestedState.setter
    def RequestedState(self, value):
        if not (isinstance(value, API_MachineStates) or value is None):
            raise DE1APITypeError("Expecting API_MachineStates")
        self._RequestedState = value


class WaterLevels (PackedAttr):

    cuuid = CUUID.WaterLevels
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, Level=None, StartFillLevel=None):
        super(WaterLevels, self).__init__()

        self.Level = Level
        self.StartFillLevel = StartFillLevel


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(WaterLevels, self).from_wire_bytes(wire_bytes, arrival_time)
        (level, start_fill_level) = unpack('>HH', wire_bytes)
        self._Level = level / 2**8
        self._StartFillLevel = start_fill_level / 2**8

        return self

    def as_wire_bytes(self):
        level = self._Level
        if level is None:
            level = 0
        start_fill_level = self._StartFillLevel
        if start_fill_level is None:
            start_fill_level = 0
        return pack('>HH',
                    u(level),
                    u(start_fill_level)
                    )

    def log_string(self):
        return 'Level: {:.2f} Refill: {:.2f}'.format(
            self._Level,
            self._StartFillLevel,
        )

    @property
    def Level(self):
        return self._Level

    @Level.setter
    def Level(self, value):
        self._Level = validate_u_p_noneok(value, 16,8)

    @property
    def StartFillLevel(self):
        return self._StartFillLevel

    @StartFillLevel.setter
    def StartFillLevel(self, value):
        self._StartFillLevel = validate_u_p_noneok(value, 16,8)


class AllSensors (PackedAttr):

    def __init__(self, ColdWater=None, HotWater=None, MixedWater=None,
                 EspressoWater=None, InCaseAmbient=None, HeatSink=None,
                 SteamHeater=None, WaterHeater=None):
        super(AllSensors, self).__init__()
        self.ColdWater = ColdWater
        self.HotWater = HotWater
        self.MixedWater = MixedWater
        self.EspressoWater = EspressoWater
        self.InCaseAmbient = InCaseAmbient
        self.HeatSink = HeatSink
        self.SteamHeater = SteamHeater
        self.WaterHeater = WaterHeater

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(AllSensors, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            self._ColdWater,
            self._HotWater,
            self._MixedWater,
            self._EspressoWater,
            self._InCaseAmbient,
            self._SteamHeater,
            self._WaterHeater,
         ) = unpack('>HHHHHHHH', wire_bytes)

        self._ColdWater = self._ColdWater / 2**8
        self._HotWater = self._HotWater / 2**8
        self._MixedWater = self._MixedWater / 2**8
        self._EspressoWater = self._EspressoWater / 2**8
        self._InCaseAmbient = self._InCaseAmbient / 2**8
        self._SteamHeater = self._SteamHeater / 2**8
        self._WaterHeater = self._WaterHeater / 2**8

        return self

    def as_wire_bytes(self):
        raise NotImplementedError

    def log_string(self):
        return 'Cold: {:.2f} Hot: {:.2f} Mix: {:.2f}' \
            'Espresso: {:.2f} Case: {:.2f} Steam: {:.2f} Water: {:.2f}'.format(
            self._ColdWater,
            self._HotWater,
            self._MixedWater,
            self._EspressoWater,
            self._InCaseAmbient,
            self._SteamHeater,
            self._WaterHeater,
        )

    @property
    def ColdWater(self):
        return self._ColdWater

    @ColdWater.setter
    def ColdWater(self, value):
        self._ColdWater = validate_u_p_noneok(value, 16, 8)

    @property
    def HotWater(self):
        return self._HotWater

    @HotWater.setter
    def HotWater(self, value):
        self._HotWater = validate_u_p_noneok(value, 16, 8)

    @property
    def MixedWater(self):
        return self._MixedWater

    @MixedWater.setter
    def MixedWater(self, value):
        self._MixedWater = validate_u_p_noneok(value, 16, 8)

    @property
    def EspressoWater(self):
        return self._EspressoWater

    @EspressoWater.setter
    def EspressoWater(self, value):
        self._EspressoWater = validate_u_p_noneok(value, 16, 8)

    @property
    def InCaseAmbient(self):
        return self._InCaseAmbient

    @InCaseAmbient.setter
    def InCaseAmbient(self, value):
        self._InCaseAmbient = validate_u_p_noneok(value, 16, 8)

    @property
    def HeatSink(self):
        return self._HeatSink

    @HeatSink.setter
    def HeatSink(self, value):
        self._HeatSink = validate_u_p_noneok(value, 16, 8)

    @property
    def SteamHeater(self):
        return self._SteamHeater

    @SteamHeater.setter
    def SteamHeater(self, value):
        self._SteamHeater = validate_u_p_noneok(value, 16, 8)

    @property
    def WaterHeater(self):
        return self._WaterHeater

    @WaterHeater.setter
    def WaterHeater(self, value):
        self._WaterHeater = validate_u_p_noneok(value, 16, 8)


# TODO; T_StoredShots, u1, NumberOfStoredShots (DE1 unimplemented?)


class TotalVOrWFlags (enum.IntFlag):
    UseVolume = 0x0000
    UseWeight = 0x8000


# TODO: TotalVOrW (DE1 unimplemented?)


class FrameFlags (enum.IntFlag):
    CtrlF       = 0x01  # Flow (or pressure)
    DoCompare   = 0x02  # Early exit if compare is true
    DC_GT       = 0x04  # Set for greater than coparison
    DC_CompF    = 0x08  # Compare flow (or pressure)
    TMixTemp    = 0x10  # Disable shower-head compensation (target MixTemp)
    Interpolate = 0x20  # Ramp to target (or jump)
    IgnoreLimit = 0x40  # Ignore minimum pressure and maximum flow settings

    DontInterpolate = 0x00
    CtrlP           = 0x00
    DC_CompP        = 0x00
    DC_LT           = 0x00
    TBasketTemp     = 0x00

    DontCompare     = 0x00
    ObserveLimit    = 0x00

    def not_flag_name(self):
        """
        Only works for bit-set flags, but only needed there
        """
        map = {
            FrameFlags.CtrlF:       'CtrlP',
            FrameFlags.DoCompare:   'DontCompare',
            FrameFlags.DC_GT:       'DC_LT',
            FrameFlags.DC_CompF:    'DC_CompP',
            FrameFlags.TMixTemp:    'TBasketTemp',
            FrameFlags.Interpolate: 'DontInterpolate',
            FrameFlags.IgnoreLimit: 'ObserveLimit',
        }
        return map.get(self, f"NOT{self.name}")




class ShotFrame (PackedAttr):

    def __init__(self, Flag=None, SetVal=None, Temp=None,
                 FrameLen=None, TriggerVal=None, MaxVol=None):
        super(ShotFrame, self).__init__()
        self.Flag = Flag
        self.SetVal = SetVal
        self.Temp = Temp
        self.FrameLen = FrameLen
        self.TriggerVal = TriggerVal
        self.MaxVol = MaxVol

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotFrame, self).from_wire_bytes(wire_bytes, arrival_time)
        (self._Flag,
        self._SetVal,
        self._Temp,
        self._FrameLen,
        self._TriggerVal,
        self._MaxVol,
         ) = unpack('>BBBBBH', wire_bytes)

        self._SetVal = self._SetVal / 2**4
        self._Temp = self._Temp / 2
        self._FrameLen = f8_1_7_decode(self._FrameLen)
        self._TriggerVal = self._TriggerVal / 2**4

        return self

    def as_wire_bytes(self):
        return pack('>BBBBBH',
                    self._Flag,
                    p4(self._SetVal),
                    p1(self._Temp),
                    f8_1_7(self._FrameLen),
                    p4(self._TriggerVal),
                    p0(self._MaxVol),
                    )

    def log_string(self):
        flag_list = []
        for flag in FrameFlags:
            if flag.value and self._Flag & flag.value:
                flag_list.append(flag.name)
            elif flag.value:
                flag_list.append(flag.not_flag_name())
        if len(flag_list) > 1:
            flags = ','.join(flag_list)
        else:
            flags = '(none)'
        return '{} SetVal: {} Temp: {} Len: {} Trigger: {} MaxVol: {}'.format(
            flags,
            self._SetVal,
            self._Temp,
            self._FrameLen,
            self._TriggerVal,
            self._MaxVol,
        )

    @property
    def Flag(self):
        return self._Flag

    @Flag.setter
    def Flag(self, value):
        self._Flag = validate_u_p_noneok(value, 8, 0)

    @property
    def SetVal(self):
        return self._SetVal

    @SetVal.setter
    def SetVal(self, value):
        self._SetVal = validate_u_p_noneok(value, 8, 4)

    @property
    def Temp(self):
        return self._Temp

    @Temp.setter
    def Temp(self, value):
        self._Temp = validate_u_p_noneok(value, 8, 1)

    @property
    def FrameLen(self):
        return self._FrameLen

    @FrameLen.setter
    def FrameLen(self, value):
        self._FrameLen = validate_f8_1_7_noneok(value)

    @property
    def TriggerVal(self):
        return self._TriggerVal

    @TriggerVal.setter
    def TriggerVal(self, value):
        self._TriggerVal = validate_u_p_noneok(value, 8, 4)

    @property
    def MaxVol(self):
        return self._MaxVol

    @MaxVol.setter
    def MaxVol(self, value):
        self._MaxVol = validate_u_p_noneok(value, 10, 0)


class ShotExtFrame (PackedAttr):

    def __init__(self, MaxFlowOrPressure=None, MaxForPRange=None):
        super(ShotExtFrame, self).__init__()
        self.MaxFlowOrPressure = MaxFlowOrPressure
        self.MaxFoPRange = MaxForPRange

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotExtFrame, self).from_wire_bytes(wire_bytes, arrival_time)
        (val, rng) = unpack('BBxxxxx', wire_bytes)
        self._MaxFlowOrPressure = val / 2**4
        self._MaxFoPRange = rng / 2**4

        return self

    def as_wire_bytes(self):
        return pack('BBxxxxx',
                    p4(self._MaxFlowOrPressure),
                    p4(self._MaxFoPRange)
                    )

    def log_string(self):
        return 'Limit: {:.2f} Range: {:.2f}'.format(
            self._MaxFlowOrPressure,
            self._MaxFoPRange,
        )

    @property
    def MaxFlowOrPressure(self):
        return self._MaxFlowOrPressure

    @MaxFlowOrPressure.setter
    def MaxFlowOrPressure(self, value):
        self._MaxFlowOrPressure = validate_u_p_noneok(value, 8, 4)

    @property
    def MaxFoPRange(self):
        return self._MaxFoPRange

    @MaxFoPRange.setter
    def MaxFoPRange(self, value):
        self._MaxFoPRange = validate_u_p_noneok(value, 8, 4)


class ShotTail (PackedAttr):

    def __init__(self, MaxTotalVolume=None, ignore_pi=True):
        super(ShotTail, self).__init__()
        self.MaxTotalVolume = MaxTotalVolume
        self.ignore_pi = ignore_pi

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotTail, self).from_wire_bytes(wire_bytes, arrival_time)
        (value) = unpack('Hxxxxx', wire_bytes)
        self._MaxTotalVolume = value & 0x03ff
        self._ignore_pi = bool(value & 8000)

        return self

    def as_wire_bytes(self):
        value = p0(self._MaxTotalVolume)
        if not isinstance(self._ignore_pi, bool):
            raise DE1APIValueError("Expecting a bool for ignore_pi")
        if self._ignore_pi:
            value += 0x8000
        return pack('Hxxxxx', value)

    def log_string(self):
        return 'Limit: {} ignore_pi: {}'.format(
            self._MaxTotalVolume,
            self._ignore_pi,
        )

    @property
    def MaxTotalVolume(self):
        return self._MaxTotalVolume

    @MaxTotalVolume.setter
    def MaxTotalVolume(self, value):
        self._MaxTotalVolume = validate_u_p_noneok(
            value & 0x03ff, 10, 0
        )

    @property
    def ignore_pi(self):
        return self._ignore_pi

    @ignore_pi.setter
    def ignore_pi(self, value):
        if value is None:
            self._ignore_pi = None
        if isinstance(value, bool):
            self._ignore_pi = value
        if value == 0 or value == 1:
            self._ignore_pi = bool(value)
        else:
            raise DE1APIValueError("Expecting a bool for ignore_pi")


MAX_FRAMES = 20


class ShotDescHeader (PackedAttr):

    def __init__(self, HeaderV=None, NumberOfFrames=None,
                 NumberOfPreinfuseFrames=None,
                 MinimumPressure=None, MaximumFlow=None):
        super(ShotDescHeader, self).__init__()
        self.HeaderV = HeaderV
        # Declare internals directly so they can be cross-checked later
        self._NumberOfFrames = NumberOfFrames
        self._NumberOfPreinfuseFrames = NumberOfPreinfuseFrames
        self._check_frame_numbers()
        self._MinimumPressure = None
        self._MaximumFlow = None

        self.MinimumPressure = MinimumPressure
        self.MaximumFlow = MaximumFlow


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotDescHeader, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            self._HeaderV,
            self._NumberOfFrames,
            self._NumberOfPreinfuseFrames,
            self._MinimumPressure,
            self._MaximumFlow,
        ) = unpack('>BBBBB', wire_bytes)

        self._MinimumPressure = self._MinimumPressure / 2**4
        self._MaximumFlow = self._MaximumFlow / 2**4

        return self

    def as_wire_bytes(self):
        self._check_frame_numbers()
        return pack('>BBBBB',
                    p0(self._HeaderV),
                    p0(self._NumberOfFrames),
                    p0(self._NumberOfPreinfuseFrames),
                    p4(self._MinimumPressure),
                    p4(self._MaximumFlow),
                    )

    def log_string(self):
        return 'V{} Total: {} PI: {} MinPress {:.2f} MaxFlow {:.2f}'.format(
            self._HeaderV,
            self._NumberOfFrames,
            self._NumberOfPreinfuseFrames,
            self._MinimumPressure,
            self._MaximumFlow,
        )

    @property
    def HeaderV(self):
        return self._HeaderV

    @HeaderV.setter
    def HeaderV(self, value):
        if value != 1 and value is not None:  # "Set to 1 for this type of shot description"
            raise DE1APIValueError("HeaderV must be 1 at this time")
        self._HeaderV = value

    @property
    def NumberOfFrames(self):
        return self._NumberOfFrames

    @NumberOfFrames.setter
    def NumberOfFrames(self, value):
        self._check_frame_numbers(nf=value)
        self._NumberOfFrames = value

    @property
    def NumberOfPreinfuseFrames(self):
        return self._NumberOfPreinfuseFrames

    @NumberOfPreinfuseFrames.setter
    def NumberOfPreinfuseFrames(self, value):
        self._check_frame_numbers(npi=value)
        self._NumberOfPreinfuseFrames = value

    @property
    def MinimumPressure(self):
        return self._MinimumPressure

    @MinimumPressure.setter
    def MinimumPressure(self, value):
        self._MinimumPressure = validate_u_p_noneok(value, 8, 4)

    @property
    def MaximumFlow(self):
        return self._MaximumFlow

    @MaximumFlow.setter
    def MaximumFlow(self, value):
        self._MaximumFlow = validate_u_p_noneok(value, 8, 4)

    def _check_frame_numbers(self, npi=None, nf=None):
        if npi is None:
            npi = self._NumberOfPreinfuseFrames
        if nf is None:
            nf = self._NumberOfFrames
        if npi is not None:
            if npi > MAX_FRAMES:
                raise DE1APITooManyFramesError(f"{MAX_FRAMES}-frame limit")
            if nf is not None and npi > nf:
                raise DE1APIValueError(
                    "Number of preinfuse frames must not exceed number of frames")
        if nf is not None and nf > MAX_FRAMES:
            raise DE1APITooManyFramesError(f"{MAX_FRAMES}-frame limit")



# TODO: Deprecated (DE1 unimplemented?)
    """
    CUUID.Deprecated
    """

# class ShotDesc:
#   # Noted as what was on Deprecated before


class HeaderWrite (PackedAttr):

    cuuid = CUUID.HeaderWrite
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, Header=None):
        super(HeaderWrite, self).__init__()

        self.Header = Header

    def as_wire_bytes(self):
        return self._Header.as_wire_bytes()

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(HeaderWrite, self).from_wire_bytes(wire_bytes, arrival_time)
        self._Header.from_wire_bytes(wire_bytes, arrival_time)

        return self

    def log_string(self):
        return self._Header.log_string()

    @property
    def Header(self):
        return self._Header

    @Header.setter
    def Header(self, value):
        if value is None:
            value = ShotDescHeader()
        if not isinstance(value, ShotDescHeader):
            raise DE1APITypeError("Expected ShotDescHeader")
        self._Header = value


class FrameWrite (PackedAttr):

    cuuid = CUUID.FrameWrite
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, FrameToWrite: Optional[int] = None,
                 Frame: Optional[Union[ShotFrame,
                                       ShotTail,
                                       ShotExtFrame]] = None):
        super(FrameWrite, self).__init__()

        self._FrameToWrite = FrameToWrite
        self._Frame = Frame

    def as_wire_bytes(self):
        retval = bytearray(pack('>B', p0(self._FrameToWrite)))
        retval.extend(self._Frame.as_wire_bytes())
        return retval

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        raise NotImplementedError

    def log_string(self):
        return 'Frame #{} {}'.format(
            self._FrameToWrite,
            self._Frame.log_string()
        )

    @property
    def FrameToWrite(self):
        raise NotImplementedError

    @FrameToWrite.setter
    def FrameToWrite(self, value):
        raise NotImplementedError

    @property
    def Frame(self):
        raise NotImplementedError

    @Frame.setter
    def Frame(self, value):
        raise NotImplementedError


class FrameWrite_ShotFrame(FrameWrite):

    def __init__(self, FrameToWrite: Optional[int] = None,
                 Frame: Optional[ShotFrame] = None):
        super(FrameWrite_ShotFrame, self).__init__(FrameToWrite, Frame)


    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(FrameWrite_ShotFrame, self).from_wire_bytes(wire_bytes,
                                                arrival_time)
        self.FrameToWrite = unpack('>B', wire_bytes[0:1])[0]
        self.Frame = ShotFrame().from_wire_bytes(wire_bytes[1:],
                                                 arrival_time)

        return self

    @property
    def FrameToWrite(self):
        return self._FrameToWrite

    @FrameToWrite.setter
    def FrameToWrite(self, value):
        if value is not None and not (
                (0 <= value < 20)
        ):
            raise DE1APIValueError(
                f"20-frame limit ({value})"
            )
        self._FrameToWrite = value

    @property
    def Frame(self):
        return self._Frame

    @Frame.setter
    def Frame(self, value):
        if not (isinstance(value, (ShotFrame,
                                   type(None)))):
            raise DE1APITypeError("Expecting ShotFrame")
        self._Frame = value


class FrameWrite_ShotExtFrame(FrameWrite):

    def __init__(self, FrameToWrite: Optional[int] = None,
                 Frame: Optional[ShotFrame] = None):
        super(FrameWrite_ShotExtFrame, self).__init__(FrameToWrite, Frame)

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(FrameWrite_ShotExtFrame, self).from_wire_bytes(wire_bytes,
                                                             arrival_time)
        self.FrameToWrite = unpack('>B', wire_bytes[0:1])[0]
        self.Frame = FrameWrite_ShotExtFrame().from_wire_bytes(wire_bytes[1:],
                                                               arrival_time)

        return self

    @property
    def FrameToWrite(self):
        return self._FrameToWrite

    @FrameToWrite.setter
    def FrameToWrite(self, value):
        if value is not None and not (
                (32 <= value < 52)
        ):
            raise DE1APIValueError(
                f"20-frame limit over 32-frame offset ({value})"
            )
        self._FrameToWrite = value

    @property
    def Frame(self):
        return self._Frame

    @Frame.setter
    def Frame(self, value):
        if not (isinstance(value, (ShotExtFrame,
                                   type(None)))):
            raise DE1APITypeError("Expecting ShotExtFrame")
        self._Frame = value



class FrameWrite_ShotTail(FrameWrite):

    def __init__(self, FrameToWrite: Optional[int] = None,
                 Frame: Optional[ShotTail] = None):
        super(FrameWrite_ShotTail, self).__init__(FrameToWrite, Frame)

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(FrameWrite_ShotTail, self).from_wire_bytes(wire_bytes,
                                                         arrival_time)
        self.FrameToWrite = unpack('>B', wire_bytes[0:1])[0]
        self.Frame = ShotTail().from_wire_bytes(wire_bytes[1:],
                                                arrival_time)

        return self

    @property
    def FrameToWrite(self):
        return self._FrameToWrite

    @FrameToWrite.setter
    def FrameToWrite(self, value):
        if value is not None and not (
                (0 < value <= 20)
        ):
            raise DE1APIValueError(
                f"20-frame limit ({value})"
            )
        self._FrameToWrite = value

    @property
    def Frame(self):
        return self._Frame

    @Frame.setter
    def Frame(self, value):
        if not (isinstance(value, (ShotTail, type(None)))):
            raise DE1APITypeError("Expecting ShotTail")
        self._Frame = value


class ShotState (PackedAttr):

    def __init__(self, GroupPressure=None, GroupFlow=None,
                 MixTemp=None, HeadTemp=None,
                 SetMixTemp=None, SetHeadTemp=None,
                 SetGroupPressure=None, SetGroupFlow=None,
                 FrameNumber=None, SteamTemp=None):
        super(ShotState, self).__init__()
        self.GroupPressure = GroupPressure
        self.GroupFlow = GroupFlow
        self.MixTemp = MixTemp
        self.HeadTemp = HeadTemp
        self.SetMixTemp = SetMixTemp
        self.SetHeadTemp = SetHeadTemp
        self.SetGroupPressure = SetGroupPressure
        self.SetGroupFlow = SetGroupFlow
        self.FrameNumber = FrameNumber
        self.SteamTemp = SteamTemp

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotState, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            gp, gf, mt, hth, htl, smt, sht, sgp, sgf, fn, st
        ) = unpack('>HHHBHHHBBBB', wire_bytes)
        self._GroupPressure = gp / 2 ** 12
        self._GroupFlow = gf / 2 ** 12
        self._MixTemp = mt / 2 ** 8
        self._HeadTemp = hth + (htl / 2 ** 16)
        self._SetMixTemp = smt / 2 ** 8
        self._SetHeadTemp = sht / 2 ** 8
        self._SetGroupPressure = sgp / 2 ** 4
        self._SetGroupFlow = sgf / 2 ** 4
        self._FrameNumber = fn
        self._SteamTemp = st

        return self

    def as_wire_bytes(self):
        raise NotImplementedError

    def log_string(self):
        return 'P: {:.2f} F: {:.2f} ' \
               'Mix: {:.2f} Head: {:.2f} ' \
               'SetMix: {:.2f} SetHead: {:.2f} ' \
               'SetP: {:.2f} SetF: {:.2f} ' \
               'Frame: {} Steam: {}'.format(
            self._GroupPressure,
            self._GroupFlow,
            self._MixTemp,
            self._HeadTemp,
            self._SetMixTemp,
            self._SetHeadTemp,
            self._SetGroupPressure,
            self._SetGroupFlow,
            self._FrameNumber,
            self._SteamTemp,
        )


    @property
    def GroupPressure(self):
        return self._GroupPressure

    @GroupPressure.setter
    def GroupPressure(self, value):
        self._GroupPressure = validate_u_p_noneok(value, 16, 12)

    @property
    def GroupFlow(self):
        return self._GroupFlow

    @GroupFlow.setter
    def GroupFlow(self, value):
        self._GroupFlow = validate_u_p_noneok(value, 16, 12)

    @property
    def MixTemp(self):
        return self._MixTemp

    @MixTemp.setter
    def MixTemp(self, value):
        self._MixTemp = validate_u_p_noneok(value, 16, 8)

    @property
    def HeadTemp(self):
        return self._HeadTemp

    @HeadTemp.setter
    def HeadTemp(self, value):
        self._HeadTemp = validate_u_p_noneok(value, 24, 16)

    @property
    def SetMixTemp(self):
        return self._SetMixTemp

    @SetMixTemp.setter
    def SetMixTemp(self, value):
        self._SetMixTemp = validate_u_p_noneok(value, 16, 8)

    @property
    def SetHeadTemp(self):
        return self._SetHeadTemp

    @SetHeadTemp.setter
    def SetHeadTemp(self, value):
        self._SetHeadTemp = validate_u_p_noneok(value, 16, 8)

    @property
    def SetGroupPressure(self):
        return self._SetGroupPressure

    @SetGroupPressure.setter
    def SetGroupPressure(self, value):
        self._SetGroupPressure = validate_u_p_noneok(value, 8, 4)

    @property
    def SetGroupFlow(self):
        return self._SetGroupFlow

    @SetGroupFlow.setter
    def SetGroupFlow(self, value):
        self._SetGroupFlow = validate_u_p_noneok(value, 8, 4)

    @property
    def FrameNumber(self):
        return self._FrameNumber

    @FrameNumber.setter
    def FrameNumber(self, value):
        self._FrameNumber = validate_u_p_noneok(value, 8, 0)

    @property
    def SteamTemp(self):
        return self._SteamTemp

    @SteamTemp.setter
    def SteamTemp(self, value):
        self._SteamTemp = validate_u_p_noneok(value, 8, 0)


class ShotSample (PackedAttr):

    cuuid = CUUID.ShotSample
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, SampleTime=None, State=None):
        super(ShotSample, self).__init__()

        self.SampleTime = SampleTime
        self.ShotState = State

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(ShotSample, self).from_wire_bytes(wire_bytes, arrival_time)
        self.SampleTime = unpack('>H', wire_bytes[0:2])[0]
        self.ShotState = ShotState().from_wire_bytes(wire_bytes[2:], arrival_time)

        return self

    def log_string(self):
        return 'Clock: {}: {}'.format(self._SampleTime, self._State.log_string())

    @property
    def SampleTime(self):
        return self._SampleTime

    @SampleTime.setter
    def SampleTime(self, value):
        self._SampleTime = validate_u_p_noneok(value, 16, 0)

    @property
    def ShotState(self):
        return self._State

    @ShotState.setter
    def ShotState(self, value):
        if not (isinstance(value, ShotState) or value is None):
            raise DE1APITypeError("Expected ShotState")
        if value is None:
            value = ShotState()
        self._State = value

    #
    # Convenience methods to go straight to the State
    #

    @property
    def GroupPressure(self):
        return self._State.GroupPressure

    @property
    def GroupFlow(self):
        return self._State.GroupFlow

    @property
    def MixTemp(self):
        return self._State.MixTemp

    @property
    def HeadTemp(self):
        return self._State.HeadTemp

    @property
    def SetMixTemp(self):
        return self._State.SetMixTemp

    @property
    def SetHeadTemp(self):
        return self._State.SetHeadTemp

    @property
    def SetGroupPressure(self):
        return self._State.SetGroupPressure

    @property
    def SetGroupFlow(self):
        return self._State.SetGroupFlow

    @property
    def FrameNumber(self):
        return self._State.FrameNumber

    @property
    def SteamTemp(self):
        return self._State.SteamTemp


# TODO: ShotData (DE1 unimplemented?)


# TODO: ShotDirectory (DE1 unimplemented?)
    """
    CUUID.ShotDirectory
    """

class FWImageInfo (PackedAttr):

    def __init__(self, Version=None, Hash=None):
        super(FWImageInfo, self).__init__()
        self.Version = Version
        self.Hash = Hash

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(FWImageInfo, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            self._Version,
            self._Hash,
        ) = unpack('>IQ', wire_bytes)

        return self

    def as_wire_bytes(self):
        return pack('>IQ',
                    u(self._Version),
                    u(self._Hash),
                    )

    def log_string(self):
        return 'Version: {} Hash: {}'.format(self._Version, self._Hash)

    @property
    def Version(self):
        return self._Version

    @Version.setter
    def Version(self, value):
        self._Version = validate_u_p_noneok(value, 32, 0)

    @property
    def Hash(self):
        return self._Hash

    @Hash.setter
    def Hash(self, value):
        self._Hash = validate_u_p_noneok(value, 64, 0)


# TODO: FirmwareImages (DE1 unimplemented?)


class MoveMMRWindow (PackedAttr):

    def __init__(self, Offset=None, Len=None):
        super(MoveMMRWindow, self).__init__()
        self.Offset = Offset
        self.Len = Len

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(MoveMMRWindow, self).from_wire_bytes(wire_bytes, arrival_time)
        (
            self._Offset,
            self._Len
        ) = unpack('IB', wire_bytes)

        return self

    def as_wire_bytes(self):
        return pack('IB', u(self._Len), p0(self._Offset))

    def log_string(self):
        return 'Offset: {} Len: {}'.format(self._Offset, self._Len)

    @property
    def Offset(self):
        return self._Offset

    @Offset.setter
    def Offset(self, value):
        self._Offset = validate_u_p_noneok(value, 32, 0)

    @property
    def Len(self):
        return self._Len

    @Len.setter
    def Len(self, value):
        self._Len = validate_u_p_noneok(value, 64, 0)


class MMRData (PackedAttr):
    """
    This represents generic, MMR data
    """

    def __init__(self, Len=None, Address=None,
                 addr_high=None, addr_low=None,
                 Data=None):
        """
        Generic MMR struct, either for read or write

        :param Len:         NB: Len is (words + 1) so 1-256 words, 4-1024 bytes
        :param Address:     Either a full, 3-byte address, or
        :param addr_high:   High byte of address and
        :param addr_low:    Low, two bytes of address
        :param Data:        Byte data
        """
        super(MMRData, self).__init__()
        if Address is not None and (addr_high is not None or addr_low is not None):
            raise MMRTypeError("Either Address or addr_high and addr_low can be specified")
        self.Len: Union[int, None] = Len
        self.addr_low: Union[int, None] = addr_low
        self.addr_high: Union[int, None] = addr_high
        self.Data: Union[bytes, bytearray, None] = Data
        self.Address: Union[int, None] = Address

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(MMRData, self).from_wire_bytes(wire_bytes, arrival_time)
        (self._Len, self._addr_high, self._addr_low) \
            = unpack('>BBH', wire_bytes[0:4])
        """
        Read request interprets Len as (words - 1) requested
        This at least won't error-out
        """
        self._Data = wire_bytes[4:(self._Len + 4)]

        return self

    # TODO: Is padding to 16 bytes a hack or not?

    def as_wire_bytes(self):
        retval = bytearray(pack('>BBH',
                                p0(self._Len),
                                int(self._addr_high),
                                int(self._addr_low))
                           )
        retval.extend(self._padded_data())
        return retval

    def log_string(self):
        if self._addr_high == 0x80:
            addr_name = MMR0x80LowAddr.for_logging(self.addr_low)
        else:
            addr_name = ""
        if len(addr_name) > 0:
            addr_name = " " + addr_name
        return '0x{:02x} ({}): 0x{:02x} {:04x}{}: {} ({})'.format(
            self._Len,
            self._Len,
            self._addr_high,
            self._addr_low,
            addr_name,
            data_as_hex(self._Data),
            len(self._Data),
        )

    @property
    def Len(self):
        return self._Len

    @Len.setter
    def Len(self, value):
        self._Len = validate_u_p_noneok(value, 8, 0)

    @property
    def Address(self):
        if self._addr_high and self.addr_low:
            return (self._addr_high << 16) + self._addr_low
        else:
            return None

    @Address.setter
    def Address(self, value):
        addr = validate_u_p_noneok(value, 24, 0)
        if addr is not None:
            self.addr_high = (addr & 0xff0000) >> 16
            self.addr_low = addr & 0x00ffff

    @property
    def addr_high(self):
        return self._addr_high

    @addr_high.setter
    def addr_high(self, value):
        self._addr_high = validate_u_p_noneok(value, 8, 0)

    @property
    def addr_low(self):
        return self._addr_low

    @addr_low.setter
    def addr_low(self, value):
        self._addr_low = validate_u_p_noneok(value, 16, 0)

    @property
    def Data(self):
        return self._Data

    @Data.setter
    def Data(self, value):
        if value is not None:
            if not isinstance(value, (bytes, bytearray)):
                raise MMRTypeError("Expected bytes or bytearray")
            if len(value) > 16:
                raise MMRTypeError("MMRData is limited to 16 bytes")
        self._Data = value

    def _padded_data(self):
        if self._Data is None:
            retval = bytearray([0] * 16)
        else:
            retval = bytearray(self._Data)
            if len(retval) < 16:
                retval.extend([0] * (16 - len(retval)))
            if len(retval) > 16:
                raise MMRDataTooLongError("MMRData is limited to 16 bytes")
        return retval


class ReadFromMMR (MMRData):
    """
    An MMR read request interprets the Len field as (words + 1) requested
    A read response interprets it as valid bytes in the payload

    NB: Default for from_response is
        False for ReadFromMMR() -- likely an outgoing request
        True for ReadFromMMR().from_bytes() -- likely an incoming response
            though will not override an already-set value
    """

    cuuid = CUUID.ReadFromMMR
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, Len=None, Address=None,
                 addr_high=None, addr_low=None,
                 Data=None, from_response=False):

        # TODO: Remove this hack:
        if Len is not None and not isinstance(Len, int):
            tb = "".join(traceback.format_stack(limit=3))
            intLen = int(Len)
            if intLen != Len:
                logger.error(f"Len {Len} is not an int:\n{tb}")
            else:
                logger.info(f"Len {Len} is not an int:\n{tb}")
            Len = intLen

        super(ReadFromMMR, self).__init__(Len=Len, Address=Address,
                    addr_high=addr_high, addr_low=addr_low, Data=Data)

        self._from_response = from_response
        if Len is not None:
            if not self._from_response:
                if not 0 <= Len <= 255:
                    raise MMRValueError(
                        "MMR read requests are limited to 255 + 1 words"
                    )
            elif Len is not None:
                if not 0 <= Len < 16:
                    raise MMRValueError(
                        "MMR read responses are limited to 16 bytes"
                    )


    def from_wire_bytes(self, wire_bytes, arrival_time=None,
                        from_response=True):
        super(ReadFromMMR, self).from_wire_bytes(wire_bytes, arrival_time)
        if from_response:
            self._Data = wire_bytes[4:(self._Len + 4)]
        else:
            # No information on how long, so take what's there
            # super() only takes Len bytes, which may be 0
            # on a one-word read request
            self._Data = wire_bytes[4:]

        return self

    @property
    def is_within_debug_log(self):
        if self.Address is None:
            return False
        if self._from_response:
            end = self.addr_low + self.Len - 1
        else:
            end = self.addr_low + 4 * self.Len - 1
        return (
                (MMR0x80LowAddr.DEBUG_BUFFER
                 <= self.addr_low < MMR0x80LowAddr.DEBUG_CONFIG)
                and (MMR0x80LowAddr.DEBUG_BUFFER
                     <= end < MMR0x80LowAddr.DEBUG_CONFIG)
                and self.addr_high == 0x80
        )


class WriteToMMR (MMRData):

    cuuid = CUUID.WriteToMMR
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, Len=None, Address=None,
                 addr_high=None, addr_low=None,
                 Data=None):

        if Len is None and Data is not None:
            Len = len(Data)

        super(WriteToMMR, self).__init__(Len=Len, Address=Address,
                 addr_high=addr_high, addr_low=addr_low, Data=Data)

        self._check_data_len_consistent()


    # Len and Data consistent at creation
    # Len consistent if Data not None
    # Data consistent if Len is not None

    def _check_data_len_consistent(self, d=None, given_len=None):
        if d is None:
            d = self._Data
        if given_len is None:
            given_len = self._Len

        if (given_len is not None) and (given_len > 16):
            raise MMRValueError(
                f"MMR writes are limited to 16 bytes ({given_len} requested)"
            )

        if (d is not None) and (len(d) > 16):
            raise MMRValueError(
                "MMR writes are limited to 16 bytes (len(d) data length)"
            )

        if (d is not None) and (given_len is not None) \
                and (len(d) != given_len):
            raise MMRValueError(
                f"MMR write Len of {given_len} is not length of data ({len(d)}"
            )


# TODO: ShotMapRequest (DE1 unimplemented?)
    """
    CUUID.ShotMapRequest
    """


class FWErrorMapRequest(enum.IntEnum):
    Ignore = 0x0
    ReportFirst = 0xffffff
    ReportNext = 0xfffffe

class FWErrorMapResponse(enum.IntEnum):
    NoneFound = 0xfffffd

class FWMapRequest(PackedAttr):
    """
    See also FWMapRequestResponse

    // Request that a firmware image be put in the memory mapped region for later reading
    U16P0 WindowIncrement;  // Every time the MMR is read, add this byte offset to the MMR base address
    U8P0  FWToErase;        // If this field is non-zero, erase the firmware slot in question. (1 or 2)
                            // Stays non-zero until firmware is erased
    U8P0  FWToMap;          // Either 1 or 2

    // How to use FirstError:
    // Enable Notify for this characteristic
    // Write 0xFFFFFF to FirstError, FWToMap should be set to the required image. FWErase should not be set.
    // A notify will later arrive with the first address that needs repairing.
    // Write 0xFFFFFE in order to update FirstError to the next block that needs repairing.
    // 0xFFFFFF resets the search address to 0, 0xFFFFFE does not.
    // If there are no remaining errors, the notified FirstError value will be 0xFFFFFD
    U24P0 FirstError;
    """

    cuuid = CUUID.FWMapRequest
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    # TODO: FirstError is ambiguous as 0x00 0000 is either
    #       * Response of Ignore from an erase request
    #       * An error at address 0x0 from an error search

    def __init__(self, WindowIncrement=None, FWToErase=None, FWToMap=None,
                 FirstError=None, arrival_time=None, from_response=False):
        super(FWMapRequest).__init__()

        self._WindowIncrement: Optional[int] = None
        self._FWToErase: Optional[int] = None
        self._FWToMap: Optional[int] = None
        self._FirstError: Optional[int] = None
        self._arrival_time: Optional[float] = arrival_time
        self._from_response: bool = from_response

        self.WindowIncrement = WindowIncrement
        self.FWToErase = FWToErase
        self.FWToMap = FWToMap
        self.FirstError = FirstError

    @property
    def WindowIncrement(self):
        return self._WindowIncrement

    @WindowIncrement.setter
    def WindowIncrement(self, value):
        if not isinstance(value, (int, type(None))):
            raise DE1APITypeError(
                f"WindowIncrement needs to be a non-negative integer: {value}")
        self._WindowIncrement = validate_u_p_noneok(value, 16, 0)

    def _check_inconsistent_fw_values(self):
        if (self.FWToErase in (1, 2)
                and self.FWToMap is not None
                and self.FWToErase != self.FWToMap):
            logger.warning(
                "FWToErase inconsistent with FWToMap: "
                f"{self.FWToErase} != {self.FWToMap}")

    @property
    def FWToErase(self):
        return self._FWToErase

    @FWToErase.setter
    def FWToErase(self, value):
        if value not in (0, 1, 2, None):
            raise DE1APIValueError(f"FWToErase must be 0, 1, or 2: {value}")
        if value is not None:
            value = int(value)
            if (value > 0
                    and self.FirstError is not None
                    and self.FirstError != FWErrorMapRequest.Ignore):
                raise DE1APIValueError(
                    "Erasing firmware while checking for upload errors "
                    f"to FW {value} with {self.FirstError.__repr__()}"
                )
        self._FWToErase = value
        self._check_inconsistent_fw_values()

    @property
    def FWToMap(self):
        return self._FWToMap

    @FWToMap.setter
    def FWToMap(self, value):
        if value not in (1, 2, None):
            raise DE1APIValueError(f"FWToMap must be 1 or 2: {value}")
        if value is not None:
            value = int(value)
        self._FWToMap = value
        self._check_inconsistent_fw_values()

    @property
    def FirstError(self):
        return self._FirstError

    @FirstError.setter
    def FirstError(self, value):
        if value is not None:

            if self._from_response:
                try:
                    value = FWErrorMapResponse(value)
                except ValueError:
                    pass

            else:
                try:
                    value = FWErrorMapRequest(value)
                except ValueError as e:
                    raise DE1APIValueError(e)
                if self.FWToErase > 0 and value != FWErrorMapRequest.Ignore:
                    raise DE1APIValueError(
                        "Erasing firmware while checking for upload errors: "
                        f"to FW {self.FWToErase} with {value.__repr__()}"
                    )
        self._FirstError = value

    def as_wire_bytes(self) -> Union[bytes, bytearray]:
        return pack('>HBBBH',
                    self.WindowIncrement,
                    self.FWToErase,
                    self.FWToMap,
                    self.FirstError >> 16,
                    self.FirstError & 0xffff
                    )

    def from_wire_bytes(self, wire_bytes: Union[bytes, bytearray],
                        arrival_time=None, from_response=True):
        self._from_response = from_response
        (self.WindowIncrement,
         self.FWToErase,
         self.FWToMap,
         fe_high,
         fe_low,) = unpack('>HBBBH', wire_bytes)
        self.FirstError = (fe_high << 16) + fe_low
        self._arrival_time = arrival_time
        return self

    def log_string(self):

        # TODO: Make sure the other log strings are None-safe

        if self.WindowIncrement is not None:
            wi = f"0x{self.WindowIncrement:x}"
        else:
            wi = None
        if isinstance(self.FirstError, (FWErrorMapRequest, FWErrorMapResponse)):
            fe_str = self.FirstError.__str__()
        else:
            fe_high = self.FirstError >> 16
            fe_low = self.FirstError & 0xffff
            fe_str = f"Next error: 0x{fe_high:02x} {fe_low:04x}"

        return f"WinInc: {wi} Erase: {self.FWToErase} Map: {self.FWToMap} {fe_str}"



# TODO: DeleteShotRange (DE1 unimplemented?)
    """
    CUUID.DeleteShotRange
    """

class SetTime (PackedAttr):

    cuuid = CUUID.SetTime
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, Timestamp=None):
        super(SetTime, self).__init__()

        self.Timestamp = None

    def from_wire_bytes(self, wire_bytes, arrival_time=None):
        super(SetTime, self).from_wire_bytes(wire_bytes, arrival_time)
        self.Timestamp = unpack('>Q', wire_bytes)[0]

        return self

    def as_wire_bytes(self):
        return pack('>Q', u(self.Timestamp))

    def log_string(self):
        return '{}: {}'.format(
            self.Timestamp,
            time.ctime(self.Timestamp),
        )

    @property
    def Timestamp(self):
        return self._Timestamp

    @Timestamp.setter
    def Timestamp(self, value):
        self._Timestamp = validate_u_p_noneok(value, 64, 0)

    def from_seconds(self, seconds):
        self.Timestamp = int(round(seconds))

        return self



# TODO: TestReq (DE1 unimplemented?)


# TODO: CalTargets
# TODO: CalCommand
# TODO: Calibration


"""
CUUID.Calibration
"""

class CalTargets (enum.IntEnum):
    CalFlow     = 0     # ratiometric
    CalPressure = 1     # ratiometric
    CalTemp     = 2     # differential, degrees C
    CalError    = 255   # return value indicating bad request


class CalCommand (enum.IntEnum):
    Read        = 0
    Write       = 1
    Reset       = 2     # to factory value
    ReadFactory = 3


class Calibration (PackedAttr):
    """
    Used to read and write internal DE1 calibration parameters

    The WriteKey is None, by default, which is not valid to write
    It is available for configuration through the config instance
    """

    cuuid = CUUID.Calibration
    can_read = bool(cuuid is not None and cuuid.can_read)
    can_write = bool(cuuid is not None and cuuid.can_write)
    can_notify = bool(cuuid is not None and cuuid.can_notify)
    can_write_then_return = bool(cuuid is not None
                                 and cuuid.can_write_then_return)

    def __init__(self, WriteKey = 0,
                 CalCommand: Optional[CalCommand] = None,
                 CalTarget: Optional[CalTargets] = None,
                 DE1ReportedValue = 0,
                 MeasuredVal = 0):

        super(Calibration, self).__init__()

        self.WriteKey = WriteKey
        self._cal_command = None
        self._cal_target = None
        self._reported = 0
        self._measured = 0

        self.CalCommand = CalCommand
        self.CalTarget = CalTarget
        self.DE1ReportedVal = DE1ReportedValue
        self.MeasuredVal = MeasuredVal

    @property
    def CalCommand(self):
        return self._cal_command

    @CalCommand.setter
    def CalCommand(self, value):
        if isinstance(value, CalCommand) or value is None:
            self._cal_command = value
        else:
            raise DE1APITypeError(
                f"Expected CalCommand, not {type(value)}"
            )

    @property
    def CalTarget(self):
        return self._cal_target

    @CalTarget.setter
    def CalTarget(self, value):
        if isinstance(value, CalTargets) or value is None:
            self._cal_target = value
        else:
            raise DE1APITypeError(
                f"Expected CalTarget, not {type(value)}"
            )

    @property
    def DE1ReportedVal(self):
        return self._reported

    @DE1ReportedVal.setter
    def DE1ReportedVal(self, value):
        self._reported = validate_s_p(value, 32, 16)

    @property
    def MeasuredVal(self):
        return self._measured

    @MeasuredVal.setter
    def MeasuredVal(self, value):
        self._measured = validate_s_p(value, 32, 16)

    @property
    def is_error_response(self):
        return self.CalTarget == CalTargets.CalError

    @property
    def is_offset(self):
        return self == CalTargets.CalTemp

    @property
    def is_ratio(self):
        return not self.is_offset

    def from_wire_bytes(self, wire_bytes: Union[bytes, bytearray],
                        arrival_time=None):
        super(Calibration, self).from_wire_bytes(wire_bytes, arrival_time)
        (wk, cc, ct, rv, mv) = unpack('>IBBii', wire_bytes)
        self.WriteKey = wk
        self.CalCommand = CalCommand(cc)
        self.CalTarget = CalTargets(ct)
        self.DE1ReportedVal = rv / 2**16
        self.MeasuredVal = mv / 2**16

        return self

    def as_wire_bytes(self) -> Union[bytes, bytearray]:
        if self.CalTarget is None:
            raise DE1APIValueError("No CalTarget supplied")
        if self.CalCommand is None:
            raise DE1APIValueError("No CalCommand supplied")
        if self.CalCommand == CalCommand.Write and not self.WriteKey:
            raise DE1APIValueError(
                "WriteKey needed to write Calibration data")
        return pack('>IBBii',
                    int(self.WriteKey),
                    self.CalCommand.value,
                    self.CalTarget.value,
                    p16(self.DE1ReportedVal),
                    p16(self.MeasuredVal))

    @staticmethod
    def _val_str(val):
        if int(val) == val:
            return str(val)
        else:
            # 2^16 ~ 1.5e-5
            return f"{val:.5f}"

    def log_string(self):
        if self.is_error_response:
            erf = 'ERROR: '
        else:
            erf = ''
        return "{}{} {} de1: {} meas: {}".format(
            erf,
            self.CalCommand.name,
            self.CalTarget.name,
            self._val_str(self.DE1ReportedVal),
            self._val_str(self.MeasuredVal)
        )


# End of APIDataTypes.hpp


# From comments in APIDataTypes.hpp


class MMRV13ModelCode (enum.IntEnum):
    UNSET       =  0
    DE1         =  1
    DE1PLUS     =  2
    DE1PRO      =  3
    DE1XL       =  4
    DE1CAFE     =  5


class MMRGHCInfoBitMask (enum.IntFlag):
    NONE_SET                    = 0x00
    LED_CONTROLLER_PRESENT      = 0x01
    TOUCH_CONTROLLER_PRESENT    = 0x02
    GHC_ACTIVE                  = 0x04
    FACTORY_MODE          = 0x80000000


class MMR0x80LowAddr (enum.IntEnum):
    HW_CONFIG               = 0x0000
    MODEL                   = 0x0004
    CPU_BOARD_MODEL         = 0x0008
    V13_MODEL               = 0x000c
    CPU_FIRMWARE_BUILD      = 0x0010
    DEBUG_LEN               = 0x2800
    DEBUG_BUFFER            = 0x2804
    DEBUG_CONFIG            = 0x3804
    FAN_THRESHOLD           = 0x3808
    TANK_TEMP               = 0x380c
    HEATER_UP1_FLOW         = 0x3810
    HEATER_UP2_FLOW         = 0x3814
    WATER_HEATER_IDLE_TEMP  = 0x3818
    GHC_INFO                = 0x381c
    PREF_GHC_MCI            = 0x3820
    MAX_SHOT_PRESS          = 0x3824
    TARGET_STEAM_FLOW       = 0x3828
    STEAM_START_SECS        = 0x382c
    SERIAL_NUMBER           = 0x3830
    HEATER_VOLTAGE          = 0x3834    # NB: +1000 if manually set
    HEATER_UP2_TIMEOUT      = 0x3838
    CAL_FLOW_EST            = 0x383c
    FLUSH_FLOW_RATE         = 0x3840    # 60 default
    FLUSH_TEMP              = 0x3844    # 850 default
    FLUSH_TIMEOUT           = 0x3848    # 200 default
    HOT_WATER_FLOW_RATE     = 0x384c

    LAST_KNOWN              = 0x384c        # See also FeatureFlag

    #
    # Surprisingly, properties can be added with member data
    # even with an IntEnum
    #

    def __init__(self, addr):
        # super(MMR0x80LowAddr, self).__init__(addr)
        # enum.IntEnum.__init__(addr)
        self.last_requested: Optional[float] = None
        self.last_updated: Optional[float] = None
        self._data_ready_event: asyncio.Event = asyncio.Event()
        self._data_raw: Optional[Union[bytes, bytearray]] = None
        self._data_decoded: Optional[Union[bytes, bytearray,
                                           str, int, float, bool,
                                           dict]] = None

    @property
    def can_read(self):
        return self not in {
            MMR0x80LowAddr.PREF_GHC_MCI,
            MMR0x80LowAddr.MAX_SHOT_PRESS,
        }

    @property
    def can_write(self):
        return self in {
            MMR0x80LowAddr.FAN_THRESHOLD,
            MMR0x80LowAddr.TANK_TEMP,
            MMR0x80LowAddr.HEATER_UP1_FLOW,
            MMR0x80LowAddr.HEATER_UP2_FLOW,
            MMR0x80LowAddr.WATER_HEATER_IDLE_TEMP,
            MMR0x80LowAddr.TARGET_STEAM_FLOW,
            MMR0x80LowAddr.STEAM_START_SECS,
            MMR0x80LowAddr.HEATER_VOLTAGE,   # Needed for older machines
            MMR0x80LowAddr.HEATER_UP2_TIMEOUT,
            MMR0x80LowAddr.CAL_FLOW_EST,
            MMR0x80LowAddr.FLUSH_FLOW_RATE,
            MMR0x80LowAddr.FLUSH_TEMP,
            MMR0x80LowAddr.FLUSH_TIMEOUT,
            MMR0x80LowAddr.HOT_WATER_FLOW_RATE,
        }

    @classmethod
    def in_debug_buffer(cls, addr_low):
        return cls.DEBUG_BUFFER.value <= addr_low < cls.DEBUG_CONFIG.value

    @property
    def read_once(self) -> bool:
        return self.can_read and not self.can_write \
            and not MMR0x80LowAddr.in_debug_buffer(self.value) \
            and self != MMR0x80LowAddr.CPU_FIRMWARE_BUILD

    @classmethod
    def for_logging(cls, addr_low):
        try:
            addr_name = cls(addr_low).name.title()
            # The above catches the at-start condition
        except ValueError:
            if cls.in_debug_buffer(addr_low):
                addr_name = "{}+0x{:03x}".format(
                    cls.DEBUG_BUFFER.name.title(),
                    addr_low - cls.DEBUG_BUFFER.value,
                )
            else:
                addr_name = ""
        return addr_name

    def __repr__(self):
        return "<%s.%s: 0x%04x>" % (
                self.__class__.__name__, self._name_, self._value_)


def decode_one_mmr(addr_high: int, addr_low: Union[MMR0x80LowAddr, int],
                   mmr_bytes: Union[bytes, bytearray]):

    if addr_high != 0x80:
        # Unknown how to decode
        retval = mmr_bytes

    if addr_low in {
        MMR0x80LowAddr.HW_CONFIG,
        MMR0x80LowAddr.MODEL,
        MMR0x80LowAddr.SERIAL_NUMBER,
        MMR0x80LowAddr.DEBUG_CONFIG,
    }:
        # Unknown how to decode
        retval = mmr_bytes

    elif addr_low in {
        MMR0x80LowAddr.CPU_BOARD_MODEL,
        MMR0x80LowAddr.CAL_FLOW_EST,
    }:
        val = unpack('<I', mmr_bytes)[0]
        retval = val / 1000

    elif addr_low in {
        MMR0x80LowAddr.TARGET_STEAM_FLOW,
        MMR0x80LowAddr.STEAM_START_SECS,
    }:
        val = unpack('<I', mmr_bytes)[0]
        retval = val / 100

    elif addr_low in {
        MMR0x80LowAddr.HEATER_UP1_FLOW,
        MMR0x80LowAddr.HEATER_UP2_FLOW,
        MMR0x80LowAddr.WATER_HEATER_IDLE_TEMP,
        MMR0x80LowAddr.HEATER_UP2_TIMEOUT,
        MMR0x80LowAddr.FLUSH_FLOW_RATE,
        MMR0x80LowAddr.FLUSH_TEMP,
        MMR0x80LowAddr.FLUSH_TIMEOUT,
        MMR0x80LowAddr.HOT_WATER_FLOW_RATE,
    }:
        val = unpack('<I', mmr_bytes)[0]
        retval = val / 10

    elif MMR0x80LowAddr.in_debug_buffer(addr_low):
        retval = mmr_bytes.decode('utf-8')

    elif addr_low == MMR0x80LowAddr.V13_MODEL:
        retval = MMRV13ModelCode(unpack('<I', mmr_bytes)[0])

    elif addr_low == MMR0x80LowAddr.GHC_INFO:
        val = unpack('<I', mmr_bytes)[0]
        # retval = {}
        # for bit in MMRGHCInfoBitMask:
        #     retval[bit] = val & bit > 0
        retval = MMRGHCInfoBitMask(val)

    elif addr_low in {
        MMR0x80LowAddr.PREF_GHC_MCI,
        MMR0x80LowAddr.MAX_SHOT_PRESS,
    } or addr_low > MMR0x80LowAddr.LAST_KNOWN:
        # These aren't implemented (fully)
        retval = unpack('<I', mmr_bytes)[0]
        logger.warning(
            "Unexpected decode requested for "
            f"0x{addr_low:04x} {retval} 0x{retval:x} "
            "(unimplemented MMR)"
        )

    else:
        retval = unpack('<I', mmr_bytes)[0]

    return retval


def pack_one_mmr0x80_write(addr_low: MMR0x80LowAddr,
                             value: Union[float, int]) -> WriteToMMR:

    if not addr_low.can_write:
        raise DE1APIValueError(
            f"Not encoding a non-writable MMR target address: {addr_low}")

    if addr_low == MMR0x80LowAddr.CAL_FLOW_EST:
        binval = pack('<I', int(round(value * 1000)))

    elif addr_low == MMR0x80LowAddr.TARGET_STEAM_FLOW:
        # Check for 0.6 to 0.8
        binval = pack('<I', int(round(value * 100)))

    elif addr_low == MMR0x80LowAddr.STEAM_START_SECS:
        # Check for 0 to 4
        binval = pack('<I', int(round(value * 100)))

    elif addr_low in (
        MMR0x80LowAddr.HEATER_UP1_FLOW,
        MMR0x80LowAddr.HEATER_UP2_FLOW,
        MMR0x80LowAddr.WATER_HEATER_IDLE_TEMP,
        MMR0x80LowAddr.HEATER_UP2_TIMEOUT,
        MMR0x80LowAddr.FLUSH_FLOW_RATE,
        MMR0x80LowAddr.FLUSH_TEMP,
        MMR0x80LowAddr.FLUSH_TIMEOUT,
    ):
        binval = pack('<I', int(round(value * 10)))

    elif addr_low in (
            MMR0x80LowAddr.TANK_TEMP,  # 0-60°C ?
            MMR0x80LowAddr.FAN_THRESHOLD,
    ):
        binval = pack('<I', int(round(value)))

    else:
        raise DE1APIValueError(
            f"Not encoding an unrecognized MMR target address: {addr_low}")

    if addr_low == MMR0x80LowAddr.FAN_THRESHOLD:
        if not (0 <= value <= 60):
            logger.warning(
                f"Fan threshold seems out of range: 0 <= {value} <= 60")

    return WriteToMMR(
        addr_high=0x80,
        addr_low=addr_low,
        Data=binval,
    )



# Define the reverse mapping based on the subclasses defined
_cuuid_to_packed_attr_class = {}
for cpa in PackedAttr.__subclasses__():
    if (cuuid := cpa.cuuid) is not None:
        _cuuid_to_packed_attr_class[cuuid] = cpa


def packed_attr_from_cuuid(cuuid: CUUID,
                           wire_bytes: Optional[Union[bytes, bytearray]] = None
                           ) -> PackedAttr:
    try:
        pa = _cuuid_to_packed_attr_class[cuuid]()
        if wire_bytes is not None:
            pa = pa.from_wire_bytes(wire_bytes)
    except KeyError:
        pa = None
    return pa

