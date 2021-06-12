"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Provide a mapping from internal objects and properties, sufficient for both
creation of outgoing dict, as well as validation of incoming requests
(Resource, key, target object, property name, value type, min, max, post_execute)

Provide "mock" classes for use in inbound API process

NB: Must be imported AFTER any imports of DE1, Scale, FlowSequencer, ...
"""
import logging
import multiprocessing, multiprocessing.connection
import sys
from typing import Optional, Union, NamedTuple

from pyDE1.dispatcher.resource import Resource, RESOURCE_VERSION

# TODO: Work through main and remote thread imports

logger = logging.getLogger(multiprocessing.current_process().name)

pname = f"into {multiprocessing.current_process().name} process"

if 'pyDE1.de1' in sys.modules:
    from pyDE1.de1 import DE1
else:
    print("Importing stub for DE1", pname)
    logger.info("Importing stub for DE1")
    from pyDE1.dispatcher.stubs import DE1

if 'pyDE1.scale' in sys.modules:
    from pyDE1.scale import Scale
else:
    print("Importing stub for Scale", pname)
    logger.info("Importing stub for Scale")
    from pyDE1.dispatcher.stubs import Scale

if 'pyDE1.flow_sequencer' in sys.modules:
    from pyDE1.flow_sequencer import FlowSequencer
else:
    print("Importing stub for FlowSequencer", pname)
    logger.info("Importing stub for FlowSequencer")
    from pyDE1.dispatcher.stubs import FlowSequencer

# cpn = multiprocessing.current_process().name
# for k in sys.modules.keys():
#     if (k.startswith('pyDE1')
#             or k.startswith('bleak')
#             or k.startswith('asyncio-mqtt')):
#         print(
#             f"{cpn}: EARLY: {k}"
#         )

from pyDE1.de1.c_api import PackedAttr, MMR0x80LowAddr, get_cuuid, \
    ShotSettings, SetTime, Versions, WaterLevels

from pyDE1.de1.exceptions import DE1APIValueError

MAPPING_VERSION = "1.0.0"


class IsAt (NamedTuple):
    target: Union[type(DE1),
                  type(Scale),
                  type(FlowSequencer),
                  type(PackedAttr),
                  type(MMR0x80LowAddr)]
    attr_path: Optional[str]  # '' for MMR0x80LowAddr, None for write_only,
    v_type: type  # expected value type for type-checking
    setter_path: Optional[str] = None   # If not a property and a different path
                                        # path of setter relative to target
    read_only: Optional[bool] = False
    # write_only: attr_path=None and setter_path=setter_attribute_name


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
        target= packed_attr,
        attr_path= attr_path,
        v_type= v_type,
        setter_path= setter_path,
        read_only= not can_read,
    )


def from_mmr(mmr: MMR0x80LowAddr, v_type: type):
    # This doesn't handle can't read and can't write
    return IsAt(
        target= mmr,
        attr_path= '',
        v_type= v_type,
        read_only= not mmr.can_read
    )


MODULES_FOR_VERSIONS = (
    'pyDE1',
    'bleak',
    'asyncio-mqtt',
    'paho-mqtt'
)


import importlib.metadata  # Used for module-version lookup only

def module_versions():
    retval = {}
    for module in MODULES_FOR_VERSIONS:
        retval[module] = importlib.metadata.version(module)
    return retval


MAPPING = dict()

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

# Work from leaves back, so can be "included" by reference

# For now, these are not writable
MAPPING[Resource.DE1_ID] = {
    'name': IsAt(target=DE1, attr_path='name', v_type=str,
                 read_only=True),
    'id': IsAt(target=DE1, attr_path='address', v_type=str,
               read_only=True),
}

# NB: A single-entry tuple needs to end with a comma

MAPPING[Resource.DE1_MODE] = {
    'mode': IsAt(target=DE1, attr_path=None, setter_path='set_mode',
                 v_type=str,),
}
# TODO: de1.mode()

# DE1_PROFILE = 'de1/profile'
# DE1_PROFILES = 'de1/profiles'
# DE1_PROFILE_UPLOAD = 'de1/profile/{id}/upload'

# DE1_FIRMWARE = 'de1/firmware'
# DE1_FIRMWARES = 'de1/firmwares'
# DE1_FIRMWARE_UPLOAD = 'de1/firmware/{id}/upload'

MAPPING[Resource.DE1_CONNECTIVITY] = {
    'mode': IsAt(target=DE1, attr_path='connectivity', v_type=str,),
}

# DE1_CONTROL = 'de1/control' -- aggregate

# TODO: Work through how to get this to work

# TODO: Allow stop_at_xxxx for everything, None means don't apply

MAPPING[Resource.DE1_CONTROL_ESPRESSO] = {
    'stop_at_time': IsAt(target=FlowSequencer,
                         attr_path='espresso_control.stop_at_time',
                         v_type=Optional[float]),
    'stop_at_volume': IsAt(target=FlowSequencer,
                           attr_path='espresso_control.stop_at_volume',
                           v_type=Optional[float]),
    'stop_at_weight': IsAt(target=FlowSequencer,
                           attr_path='espresso_control.stop_at_weight',
                           v_type=Optional[float]),
    'disable_auto_tare': IsAt(target=FlowSequencer,
                              attr_path='espresso_control.disable_auto_tare',
                              v_type=bool),

    'profile_can_override_stop_limits':
        IsAt(target=FlowSequencer,
             attr_path='espresso_control.profile_can_override_stop_limits',
             v_type=bool),
    'profile_can_override_tank_temperature':
        IsAt(target=FlowSequencer,
             attr_path='espresso_control.profile_can_override_tank_temperature',
             v_type=bool),
    'first_drops_threshold':
        IsAt(target=FlowSequencer,
             attr_path='espresso_control.first_drops_threshold',
             v_type=Optional[float]),
    'last_drops_minimum_time':
        IsAt(target=FlowSequencer,
             attr_path='espresso_control.last_drops_minimum_time',
             v_type=float),
}

MAPPING[Resource.DE1_CONTROL_STEAM] = {
    'stop_at_time': IsAt(target=ShotSettings, attr_path='TargetSteamLength', v_type=int),
    'stop_at_volume': IsAt(target=FlowSequencer,
                           attr_path='steam_control.stop_at_volume',
                           v_type=Optional[float]),
    'stop_at_weight': IsAt(target=FlowSequencer,
                           attr_path='steam_control.stop_at_weight',
                           v_type=Optional[float]),
    'disable_auto_tare': IsAt(target=FlowSequencer,
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
    'stop_at_weight': IsAt(target=FlowSequencer,
                           attr_path='hot_water_control.stop_at_weight',
                           v_type=Optional[float]),
    'disable_auto_tare': IsAt(target=FlowSequencer,
                              attr_path='hot_water_control.disable_auto_tare',
                              v_type=bool),
    'temperature': IsAt(target=ShotSettings,
                        attr_path='TargetHotWaterTemp', v_type=int),
}

MAPPING[Resource.DE1_CONTROL_HOT_WATER_RINSE] = {
    'stop_at_time':
        IsAt(target=FlowSequencer,
             attr_path='hot_water_rinse_control.stop_at_time',
             v_type=Optional[float]),
    'stop_at_volume':
        IsAt(target=FlowSequencer,
             attr_path='hot_water_rinse_control.stop_at_volume',
             v_type=Optional[float]),
    'stop_at_weight':
        IsAt(target=FlowSequencer,
             attr_path='hot_water_rinse_control.stop_at_weight',
             v_type=Optional[float]),
    'disable_auto_tare':
        IsAt(target=FlowSequencer,
             attr_path='hot_water_rinse_control.disable_auto_tare', v_type=bool),
}

MAPPING[Resource.DE1_CONTROL_TANK_WATER_THRESHOLD] = {
    'temperature': IsAt(target=MMR0x80LowAddr.TANK_WATER_THRESHOLD, attr_path='', v_type=int),
}

# DE1_SETTING = 'de1/setting' -- aggregate

MAPPING[Resource.DE1_SETTING_AUTO_OFF_TIME] = {
    'time': IsAt(target=DE1, attr_path='auto_off_time',
                 v_type=Optional[float]),
}

MAPPING[Resource.DE1_SETTING_FAN_THRESHOLD] = {
    'temperature': IsAt(target=MMR0x80LowAddr.FAN_THRESHOLD, attr_path='', v_type=int),
}

MAPPING[Resource.DE1_SETTING_START_FILL_LEVEL] = {
    'start_fill_level': IsAt(target=WaterLevels, attr_path='StartFillLevel', v_type=int),
}

MAPPING[Resource.DE1_SETTING_BEFORE_FLOW] = {
    'heater_phase1_flow': IsAt(target=MMR0x80LowAddr.HEATER_PHASE1_FLOW, attr_path='', v_type=float),
    'heater_phase2_flow': IsAt(target=MMR0x80LowAddr.HEATER_PHASE2_FLOW, attr_path='', v_type=float),
    'heater_phase2_timeout': IsAt(target=MMR0x80LowAddr.HEATER_PHASE2_TIMEOUT, attr_path='', v_type=float),
    'heater_idle_temperature': IsAt(target=MMR0x80LowAddr.HEATER_IDLE_TEMPERATURE, attr_path='', v_type=float),
}

MAPPING[Resource.DE1_SETTING_STEAM] = {
    'temperature': IsAt(target=ShotSettings, attr_path='TargetSteamTemp', v_type=int),
    'flow': IsAt(target=MMR0x80LowAddr.STEAM_FLOW_RATE, attr_path='', v_type=float),
    'high_flow_time': IsAt(target=MMR0x80LowAddr.HIGH_STEAM_FLOW_TIME, attr_path='', v_type=float),
}

# TODO: What is ShotSettings.TargetGroupTemp and where does it really belong?
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
    'firmware_model': IsAt(target=MMR0x80LowAddr.FIRMWARE_MODEL, attr_path='', v_type=str),
    'firmware_build_number': IsAt(target=MMR0x80LowAddr.FIRMWARE_BUILD_NUMBER, attr_path='', v_type=int),
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
    'multiplier': IsAt(target=MMR0x80LowAddr.FLOW_CALIBRATION,
                       attr_path='', v_type=float),
}

MAPPING[Resource.SCALE_ID] = {
    'name': IsAt(target=Scale, attr_path='name', v_type=str,
                 read_only=True),
    'id': IsAt(target=Scale, attr_path='address', v_type=str,
               read_only=True),
    'type': IsAt(target=Scale, attr_path='type', v_type=str,
                 read_only=True),
}

MAPPING[Resource.SCALE_CONNECTIVITY] = {
    'mode': IsAt(target=Scale, attr_path='connectivity', v_type=str,),
}

MAPPING[Resource.SCALE_TARE] = {
    'tare': IsAt(target=Scale, attr_path='', setter_path='tare_with_bool',
                 v_type=Optional[bool])     # Accommodate None as False
}

MAPPING[Resource.SCALE_DISPLAY] = {
    'display_on': IsAt(target=Scale, attr_path='', setter_path='display_bool',
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
    # 'internal': Mapping[Resource.DE1_CALIBRATION_INTERNAL],
}

# TODO: How to handle GET if non-GET items? NaN? null?
MAPPING[Resource.DE1] = {
    'id': MAPPING[Resource.DE1_ID],
    'mode': MAPPING[Resource.DE1_MODE],
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
