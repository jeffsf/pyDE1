"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Provide a mapping from internal objects and properties, sufficient for both
creation of outgoing dict, as well as validation of incoming requests
(Resource, key, target object, property name, value type, min, max, post_execute)

As of MAPPING_VERSION 4.0.0 direct use of the class or a stub has been replaed
by use of an enum. Consumers will need to map the enum to the class.
This is due to challenges in determining if the class or the stub is needed.
"""

import importlib.util
import inspect
import sys
from enum import Enum, auto
from typing import Optional, Union, NamedTuple

import pyDE1
from pyDE1.de1.c_api import (
    PackedAttr, MMR0x80LowAddr,
    SetTime, ShotSettings, Versions, WaterLevels,
)
from pyDE1.dispatcher.resource import (
    Resource, RESOURCE_VERSION, DE1ModeEnum, ConnectivityEnum
)

MAPPING_VERSION = "4.0.1"

logger = pyDE1.getLogger('Inbound.Mapping')

# There are a handful of requests related to the DE1 and Scale
# that can be or must be handled even if the device is not ready.
# At this time, they include those in DE1_ID and SCALE_ID
# Rather than introduce great complexity to accommodate those exceptions,
#   * Move the remaining, related Scale access to ScaleProcessor
#   * Ensure that the DE1 and ScaleProcessor return meaningful values
#   * Ensure that if None is returned, that the IsAt indicates Optional[]
#   * Add the "if_not_ready" element to IsAt and check in requires_*


class TO (Enum):
    DE1 = auto()
    DiscoveredDevices = auto()
    FlowSequencer = auto()
    Scale = auto()
    ScaleProcessor = auto()
    

class IsAt(NamedTuple):
    # TODO: This list appears to miss None for Resource.SCAN (scanner.py)
    #       Maybe reference by the module?
    target: Union[type(TO),
                  type(PackedAttr),
                  type(MMR0x80LowAddr),]
    attr_path: Optional[str]  # '' for MMR0x80LowAddr, None for write_only,
    v_type: type  # expected value type for type-checking
    setter_path: Optional[str] = None   # If not a property and a different path
                                        # path of setter relative to target
    read_only: Optional[bool] = False
    # write_only: attr_path=None and setter_path=setter_attribute_name
    # internal_type used for conversion to enum
    internal_type: Optional[Union[type(DE1ModeEnum),
                                  type(ConnectivityEnum)]] = None
    # A handful of things, such as connectivity, don't need "ready"
    if_not_ready: bool = False

    @property
    def requires_connected_de1(self) -> bool:
        retval = (
            (self.target == TO.DE1 and not self.if_not_ready)
            or isinstance(self.target, MMR0x80LowAddr)
            or (inspect.isclass(self.target)
                and issubclass(self.target, PackedAttr))
        )
        return retval

    @property
    def requires_connected_scale(self) -> bool:
        retval = (
            (self.target == TO.Scale and not self.if_not_ready)
        )
        return retval


def mapping_requires(mapping: dict) -> dict:
    results = {
        'DE1': False,
        'Scale': False
    }
    return _mapping_requires_inner(mapping, results)


def _mapping_requires_inner(mapping: dict, results: dict) -> dict:
    for val in mapping.values():
        if isinstance(val, IsAt):
            if val.requires_connected_de1:
                results['DE1'] = True
            if val.requires_connected_scale:
                results['Scale'] = True

        if isinstance(val, dict):
            _mapping_requires_inner(val, results)

        # TODO: Maybe one day generify this
        if results['DE1'] and results['Scale']:
            break

    return results


# Helper to populate an IsAt for a PackedAttr
def from_packed_attr(packed_attr: PackedAttr, attr_path: str, v_type: type,
                     setter_path: Optional[str] = None):
    # get_cuuid will raise if not over-the-wire
    cuuid = get_cuuid(packed_attr)
    can_read = cuuid.can_read or cuuid.can_notify
    can_write = cuuid.can_write
    if attr_path is not None and not can_read:
        raise DE1APIValueError(
            f"Un-readable PackedAttr {packed_attr} "
            f"with attr_path set to '{attr_path}'"
        )

    return IsAt(
        target=packed_attr,
        attr_path=attr_path,
        v_type=v_type,
        setter_path=setter_path,
        read_only=not can_read,
    )


# Helper to populate an IsAt for MMR
def from_mmr(mmr: MMR0x80LowAddr, v_type: type):
    # This doesn't handle can't read and can't write
    return IsAt(
        target=mmr,
        attr_path='',
        v_type=v_type,
        read_only=not mmr.can_read
    )


MODULES_FOR_VERSIONS = (
    'pyDE1',
    'aiosqlite',
    'bleak',
    'paho-mqtt',
    'PyYAML',
    'requests',
    # Retained for backward compatibility - consider as deprecated in this list
    'asyncio-mqtt',
)

import importlib.metadata  # Used for module-version lookup only


def module_versions():
    retval = {}
    for module in MODULES_FOR_VERSIONS:
        try:
            retval[module] = importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            retval[module] = None
    return retval


MAPPING = {}

MAPPING[Resource.VERSION] = {
    'resource_version': RESOURCE_VERSION,
    'mapping_version': MAPPING_VERSION,
    'platform': sys.platform,
    'python': sys.version,
    'python_info': {
        'major': sys.version_info.major,
        'minor': sys.version_info.minor,
        'micro': sys.version_info.micro,
        'releaselevel': sys.version_info.releaselevel,
        'serial': sys.version_info.serial,
    },
    'module_versions': module_versions()
}

# "Specials" -- content-only

MAPPING[Resource.DE1_PROFILE] = IsAt(target=TO.DE1, attr_path=None,
                                     setter_path='upload_json_v2_profile',
                                     v_type=Union[bytes, bytearray])

MAPPING[Resource.DE1_FIRMWARE] = IsAt(target=TO.DE1, attr_path=None,
                                      setter_path='upload_firmware_from_content',
                                      v_type=Union[bytes, bytearray])

MAPPING[Resource.DE1_FIRMWARE_CANCEL] = IsAt(target=TO.DE1, attr_path=None,
                                             setter_path='cancel_firmware_api',
                                             v_type=Union[bytes, bytearray])

# TODO: How to reference a module-level subroutine? Use module as target?
# TODO: How to get the scan ID back to the caller

MAPPING[Resource.SCAN] = {
    'begin': IsAt(target=None, attr_path=None,
                  setter_path='scan_from_api', v_type=bool)
}

# Note: This is an async getter because of the lock
MAPPING[Resource.SCAN_DEVICES] = {
    'devices': IsAt(target=TO.DiscoveredDevices, attr_path='devices_for_json',
                    read_only=True,
                    v_type=dict)
}

# Work from leaves back, so can be "included" by reference

# For now, name is not writable
MAPPING[Resource.DE1_ID] = {
    'name': IsAt(target=TO.DE1, attr_path='name', v_type=Optional[str],
                 read_only=True,
                 if_not_ready=True),
    'id': IsAt(target=TO.DE1, attr_path='address', v_type=Optional[str],
               setter_path='change_de1_to_id',
               if_not_ready=True),
    # first_if_found, if true, will replace only if one is found
    # It is an error to be true if 'id' is present at this time
    'first_if_found': IsAt(target=TO.DE1, attr_path=None,
                           setter_path='first_if_found', v_type=bool,
                           if_not_ready=True),
}

# NB: A single-entry tuple needs to end with a comma

MAPPING[Resource.DE1_MODE] = {
    'mode': IsAt(target=TO.DE1, attr_path=None, setter_path='mode_setter',
                 v_type=str, internal_type=DE1ModeEnum),
}

MAPPING[Resource.DE1_STATE] = {
    'state': IsAt(target=TO.DE1, attr_path='state_getter',
                  read_only=True,
                  v_type=str, internal_type=str),
}

MAPPING[Resource.DE1_FEATURE_FLAGS] = {
    'feature_flags': IsAt(target=TO.DE1, attr_path='feature_flags',
                          v_type=str, read_only=True),
}

# DE1_PROFILE = 'de1/profile'
# DE1_PROFILES = 'de1/profiles'

MAPPING[Resource.DE1_PROFILE_ID] = {
    'id': IsAt(target=TO.DE1, attr_path='profile_id', v_type=str,
               setter_path='set_profile_by_id')
}

# DE1_FIRMWARE = 'de1/firmware'
# DE1_FIRMWARES = 'de1/firmwares'

MAPPING[Resource.DE1_FIRMWARE_ID] = {
    'id': IsAt(target=MMR0x80LowAddr.CPU_FIRMWARE_BUILD,
               attr_path='', v_type=int),
}

MAPPING[Resource.DE1_CONNECTIVITY] = {
    'mode': IsAt(target=TO.DE1, attr_path='connectivity',
                 setter_path='connectivity_setter', v_type=str,
                 internal_type=ConnectivityEnum,
                 if_not_ready=True),
}

# DE1_CONTROL = 'de1/control' -- aggregate
# TODO: Work through how to get the aggregate to operate


MAPPING[Resource.DE1_CONTROL_ESPRESSO] = {
    'stop_at_time': IsAt(target=TO.FlowSequencer,
                         attr_path='espresso_control.stop_at_time',
                         v_type=Optional[float]),
    'stop_at_volume': IsAt(target=TO.FlowSequencer,
                           attr_path='espresso_control.stop_at_volume',
                           v_type=Optional[float]),
    'stop_at_weight': IsAt(target=TO.FlowSequencer,
                           attr_path='espresso_control.stop_at_weight',
                           v_type=Optional[float]),
    'disable_auto_tare': IsAt(target=TO.FlowSequencer,
                              attr_path='espresso_control.disable_auto_tare',
                              v_type=bool),

    'profile_can_override_stop_limits':
        IsAt(target=TO.FlowSequencer,
             attr_path='espresso_control.profile_can_override_stop_limits',
             v_type=bool),
    'profile_can_override_tank_temperature':
        IsAt(target=TO.FlowSequencer,
             attr_path='espresso_control.profile_can_override_tank_temperature',
             v_type=bool),
    'first_drops_threshold':
        IsAt(target=TO.FlowSequencer,
             attr_path='espresso_control.first_drops_threshold',
             v_type=Optional[float]),
    'last_drops_minimum_time':
        IsAt(target=TO.FlowSequencer,
             attr_path='espresso_control.last_drops_minimum_time',
             v_type=float),
}

MAPPING[Resource.DE1_CONTROL_STEAM] = {
    'stop_at_time': IsAt(target=ShotSettings, attr_path='TargetSteamLength', v_type=int),
    'stop_at_volume': IsAt(target=TO.FlowSequencer,
                           attr_path='steam_control.stop_at_volume',
                           v_type=Optional[float]),
    'stop_at_weight': IsAt(target=TO.FlowSequencer,
                           attr_path='steam_control.stop_at_weight',
                           v_type=Optional[float]),
    'disable_auto_tare': IsAt(target=TO.FlowSequencer,
                              attr_path='steam_control.disable_auto_tare',
                              v_type=bool),
}

MAPPING[Resource.DE1_CONTROL_HOT_WATER] = {
    'stop_at_time': IsAt(target=ShotSettings,
                         attr_path='TargetHotWaterLength',
                         v_type=int),
    'stop_at_volume': IsAt(target=ShotSettings,
                           attr_path='TargetHotWaterVol',
                           v_type=int),
    'stop_at_weight': IsAt(target=TO.FlowSequencer,
                           attr_path='hot_water_control.stop_at_weight',
                           v_type=Optional[float]),
    'disable_auto_tare': IsAt(target=TO.FlowSequencer,
                              attr_path='hot_water_control.disable_auto_tare',
                              v_type=bool),
    'temperature': IsAt(target=ShotSettings,
                        attr_path='TargetHotWaterTemp', v_type=int),
}

MAPPING[Resource.DE1_CONTROL_HOT_WATER_RINSE] = {
    'stop_at_time':
        IsAt(target=TO.FlowSequencer,
             attr_path='hot_water_rinse_control.stop_at_time',
             setter_path='hot_water_rinse_control.stop_at_time_set_async',
             v_type=Optional[float]),
    'stop_at_volume':
        IsAt(target=TO.FlowSequencer,
             attr_path='hot_water_rinse_control.stop_at_volume',
             v_type=Optional[float]),
    'stop_at_weight':
        IsAt(target=TO.FlowSequencer,
             attr_path='hot_water_rinse_control.stop_at_weight',
             v_type=Optional[float]),
    'disable_auto_tare':
        IsAt(target=TO.FlowSequencer,
             attr_path='hot_water_rinse_control.disable_auto_tare', v_type=bool),
    'temperature':
        IsAt(target=MMR0x80LowAddr.FLUSH_TEMP, attr_path='', v_type=float),
    'flow':
        IsAt(target=MMR0x80LowAddr.FLUSH_FLOW_RATE, attr_path='', v_type=float),
}

MAPPING[Resource.DE1_CONTROL_TANK_WATER_THRESHOLD] = {
    'temperature': IsAt(target=MMR0x80LowAddr.TANK_TEMP, attr_path='', v_type=int),
}

# DE1_SETTING = 'de1/setting' -- aggregate

MAPPING[Resource.DE1_SETTING_AUTO_OFF_TIME] = {
    'time': IsAt(target=TO.DE1, attr_path='auto_off_time',
                 v_type=Optional[float]),
}

MAPPING[Resource.DE1_SETTING_FAN_THRESHOLD] = {
    'temperature': IsAt(target=MMR0x80LowAddr.FAN_THRESHOLD, attr_path='', v_type=int),
}

MAPPING[Resource.DE1_SETTING_START_FILL_LEVEL] = {
    'start_fill_level': IsAt(target=WaterLevels, attr_path='StartFillLevel', v_type=int),
}

MAPPING[Resource.DE1_SETTING_BEFORE_FLOW] = {
    'heater_phase1_flow': IsAt(target=MMR0x80LowAddr.HEATER_UP1_FLOW, attr_path='', v_type=float),
    'heater_phase2_flow': IsAt(target=MMR0x80LowAddr.HEATER_UP2_FLOW, attr_path='', v_type=float),
    'heater_phase2_timeout': IsAt(target=MMR0x80LowAddr.HEATER_UP2_TIMEOUT, attr_path='', v_type=float),
    'heater_idle_temperature': IsAt(target=MMR0x80LowAddr.WATER_HEATER_IDLE_TEMP, attr_path='', v_type=float),
}

MAPPING[Resource.DE1_SETTING_STEAM] = {
    'temperature': IsAt(target=ShotSettings, attr_path='TargetSteamTemp', v_type=int),
    'flow': IsAt(target=MMR0x80LowAddr.TARGET_STEAM_FLOW, attr_path='', v_type=float),
    'high_flow_time': IsAt(target=MMR0x80LowAddr.STEAM_START_SECS, attr_path='', v_type=float),
}

# TODO: What is ShotSettings.TargetGroupTemp in the current DE1 firmware
#       and where does it really belong?
MAPPING[Resource.DE1_SETTING_TARGET_GROUP_TEMP] = {
    'temperature': IsAt(target=ShotSettings, attr_path='TargetGroupTemp', v_type=int),
}

# NB: Not exposed at this time
MAPPING[Resource.DE1_DEPRECATED] = {
    'old_espresso_vol': IsAt(target=ShotSettings,
                             attr_path='TargetEspressoVol', v_type=int),
    'steam_fast_start': IsAt(target=ShotSettings,
                       attr_path='steam_setting_fast_start', v_type=bool),
    'steam_high_power': IsAt(target=ShotSettings,
                       attr_path='steam_setting_high_power', v_type=bool),
}

MAPPING[Resource.DE1_SETTING_TIME] = {
    'timestamp': IsAt(target=SetTime, attr_path='Timestamp', v_type=int),
}

# None exposed yet
MAPPING[Resource.DE1_PARAMETER_SET] = {
}

MAPPING[Resource.DE1_READ_ONCE] = {
    'hw_config_hexstr': IsAt(target=MMR0x80LowAddr.HW_CONFIG, attr_path='', v_type=str),
    'model_hexstr': IsAt(target=MMR0x80LowAddr.MODEL, attr_path='', v_type=str),
    'cpu_board_model': IsAt(target=MMR0x80LowAddr.CPU_BOARD_MODEL, attr_path='', v_type=float),
    'firmware_model': IsAt(target=MMR0x80LowAddr.V13_MODEL, attr_path='', v_type=str),
    'firmware_build_number': IsAt(target=MMR0x80LowAddr.CPU_FIRMWARE_BUILD, attr_path='', v_type=int),
    'ghc_info': IsAt(target=MMR0x80LowAddr.GHC_INFO, attr_path='', v_type=str),  # See MMRGHCInfoBitMask
    'serial_number_hexstr': IsAt(target=MMR0x80LowAddr.SERIAL_NUMBER, attr_path='', v_type=str),
    'heater_voltage': IsAt(target=MMR0x80LowAddr.HEATER_VOLTAGE, attr_path='', v_type=int),

    'version_ble': {
        'api': IsAt(target=Versions, attr_path='BLEVersion.APIVersion', v_type=int),
        'release': IsAt(target=Versions, attr_path='BLEVersion.Release', v_type=float),
        'commits': IsAt(target=Versions, attr_path='BLEVersion.Commits', v_type=int),
        'changes': IsAt(target=Versions, attr_path='BLEVersion.Changes', v_type=int),
        'blesha_hexstr': IsAt(target=Versions, attr_path='BLEVersion.BLESha', v_type=str),
    },

    'version_lv': {
        'api': IsAt(target=Versions, attr_path='LVVersion.APIVersion', v_type=int),
        'release': IsAt(target=Versions, attr_path='LVVersion.Release', v_type=float),
        'commits': IsAt(target=Versions, attr_path='LVVersion.Commits', v_type=int),
        'changes': IsAt(target=Versions, attr_path='LVVersion.Changes', v_type=int),
        'blesha_hexstr': IsAt(target=Versions, attr_path='LVVersion.BLESha', v_type=str),
    },
}

MAPPING[Resource.DE1_CALIBRATION_FLOW_MULTIPLIER] = {
    'multiplier': IsAt(target=MMR0x80LowAddr.CAL_FLOW_EST,
                       attr_path='', v_type=float),
}

MAPPING[Resource.DE1_CALIBRATION_LINE_FREQUENCY] = {
    'hz': IsAt(target=TO.DE1, attr_path='line_frequency', v_type=int)
}

MAPPING[Resource.SCALE_ID] = {
    'name': IsAt(target=TO.ScaleProcessor, attr_path='scale_name',
                 v_type=Optional[str],
                 read_only=True,
                 if_not_ready=True),
    'id': IsAt(target=TO.ScaleProcessor, attr_path='scale_address',
               v_type=Optional[str],
               setter_path='change_scale_to_id',
               if_not_ready=True),
    'type': IsAt(target=TO.ScaleProcessor, attr_path='scale_type',
                 v_type=Optional[str],
                 read_only=True,
                 if_not_ready=True),
    # first_if_found, if true, will replace only if one is found
    # It is an error to be true if 'id' is present at this time
    'first_if_found': IsAt(target=TO.ScaleProcessor, attr_path=None,
                           setter_path='first_if_found', v_type=bool,
                           if_not_ready=True),
}

MAPPING[Resource.SCALE_CONNECTIVITY] = {
    'mode': IsAt(target=TO.ScaleProcessor, attr_path='scale_connectivity',
                 setter_path="connectivity_setter", v_type=str,
                 internal_type=ConnectivityEnum,
                 if_not_ready=True),
}

MAPPING[Resource.SCALE_TARE] = {
    'tare': IsAt(target=TO.Scale, attr_path='', setter_path='tare_with_bool',
                 v_type=Optional[bool])  # Accommodate None as False
}

MAPPING[Resource.SCALE_DISPLAY] = {
    'display_on': IsAt(target=TO.Scale, attr_path='', setter_path='display_bool',
                       v_type=Optional[bool])  # Accommodate None as False
}

MAPPING[Resource.DE1_CONTROL] = {
    'espresso': MAPPING[Resource.DE1_CONTROL_ESPRESSO],
    'steam': MAPPING[Resource.DE1_CONTROL_STEAM],
    'hot_water': MAPPING[Resource.DE1_CONTROL_HOT_WATER],
    'hot_water_rinse': MAPPING[Resource.DE1_CONTROL_HOT_WATER_RINSE],
    'tank_water_threshold': MAPPING[Resource.DE1_CONTROL_TANK_WATER_THRESHOLD],
}

MAPPING[Resource.DE1_SETTING] = {
    'auto_off_time': MAPPING[Resource.DE1_SETTING_AUTO_OFF_TIME],
    'fan_threshold': MAPPING[Resource.DE1_SETTING_FAN_THRESHOLD],
    'start_fill_level': MAPPING[Resource.DE1_SETTING_START_FILL_LEVEL],
    'before_flow': MAPPING[Resource.DE1_SETTING_BEFORE_FLOW],
    'target_group_temp': MAPPING[Resource.DE1_SETTING_TARGET_GROUP_TEMP],
    'steam': MAPPING[Resource.DE1_SETTING_STEAM],
    'time': MAPPING[Resource.DE1_SETTING_TIME],
}

MAPPING[Resource.DE1_CALIBRATION] = {
    'flow_multiplier': MAPPING[Resource.DE1_CALIBRATION_FLOW_MULTIPLIER],
    'line_frequency': MAPPING[Resource.DE1_CALIBRATION_LINE_FREQUENCY],
    # 'internal': Mapping[Resource.DE1_CALIBRATION_INTERNAL],
}

MAPPING[Resource.DE1] = {
    'id': MAPPING[Resource.DE1_ID],
    'mode': MAPPING[Resource.DE1_MODE],
    'state': MAPPING[Resource.DE1_STATE],
    # profile
    # profiles
    # firmware
    # firmwares
    'connectivity': MAPPING[Resource.DE1_CONNECTIVITY],
    'control': MAPPING[Resource.DE1_CONTROL],
    'setting': MAPPING[Resource.DE1_SETTING],
    'calibration': MAPPING[Resource.DE1_CALIBRATION],
    'parameter_set': MAPPING[Resource.DE1_PARAMETER_SET],
    'read_once': MAPPING[Resource.DE1_READ_ONCE],
}

MAPPING[Resource.SCALE] = {
    'id': MAPPING[Resource.SCALE_ID],
    'connectivity': MAPPING[Resource.SCALE_CONNECTIVITY],
    'tare': MAPPING[Resource.SCALE_TARE],
    'display': MAPPING[Resource.SCALE_DISPLAY],
}

MAPPING[Resource.FLOW_SEQUENCER_SETTING] = {}

MAPPING[Resource.FLOW_SEQUENCER_PARAMETER_SET] = {}

MAPPING[Resource.FLOW_SEQUENCER] = {
    'setting': MAPPING[Resource.FLOW_SEQUENCER_SETTING],
    'parameter_set': MAPPING[Resource.FLOW_SEQUENCER_PARAMETER_SET],
}
