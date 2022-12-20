"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Enum that defines the recognized resources that the Dispatcher can access
"""

import enum

RESOURCE_VERSION = '3.9.0'


class Resource (enum.Enum):

    SCAN = 'scan'
    SCAN_DEVICES = 'scan/devices'

    LOG = 'log/{id}'
    LOGS = 'logs'

    DE1 = 'de1'

    DE1_ID = 'de1/id'

    DE1_MODE = 'de1/mode'   # Commands
    DE1_STATE = 'de1/state' # Current state and substate

    DE1_FEATURE_FLAGS = 'de1/feature_flags'

    DE1_PROFILE = 'de1/profile'
    DE1_PROFILE_ID = 'de1/profile/id'
    DE1_PROFILE_STORE = 'de1/profile/store'  # PUT to database, but not DE1
    DE1_PROFILES = 'de1/profiles'

    DE1_FIRMWARE = 'de1/firmware'
    DE1_FIRMWARE_CANCEL = 'de1/firmware/cancel'
    DE1_FIRMWARE_ID = 'de1/firmware/id'
    DE1_FIRMWARES = 'de1/firmwares'

    DE1_AVAILABILITY = 'de1/availability'
    DE1_CONNECTIVITY = 'de1/connectivity'

    DE1_CONTROL = 'de1/control'
    DE1_CONTROL_ESPRESSO = 'de1/control/espresso'
    DE1_CONTROL_STEAM = 'de1/control/steam'
    DE1_CONTROL_HOT_WATER = 'de1/control/hot_water'
    DE1_CONTROL_HOT_WATER_RINSE = 'de1/control/hot_water_rinse'
    DE1_CONTROL_TANK_WATER_THRESHOLD = 'de1/control/tank_water_threshold'

    DE1_SETTING = 'de1/setting'
    DE1_SETTING_AUTO_OFF_TIME = 'de1/setting/auto_off_time'
    DE1_SETTING_FAN_THRESHOLD = 'de1/setting/fan_threshold'
    DE1_SETTING_START_FILL_LEVEL = 'de1/setting/start_fill_level'
    DE1_SETTING_BEFORE_FLOW = 'de1/setting/before_flow'
    DE1_SETTING_TARGET_GROUP_TEMP = 'de1/setting/target_group_temp'
    DE1_SETTING_USB_OUTLET = 'de1/setting/usb_outlet'
    DE1_SETTING_REFILL_KIT = 'de1/setting/refill_kit'

    DE1_SETTING_STEAM = 'de1/setting/steam'

    DE1_DEPRECATED = 'de1/setting/tbd_name_other_shot_settings'
    DE1_SETTING_TIME = 'de1/setting/time'

    DE1_CALIBRATION = 'de1/calibration'
    DE1_CALIBRATION_LINE_FREQUENCY = 'de1/calibration/line_frequency'
    DE1_CALIBRATION_FLOW_MULTIPLIER = 'de1/calibration/flow_multiplier'
    DE1_CALIBRATION_INTERNAL = 'de1/calibration/internal'

    DE1_PARAMETER_SET = 'de1/parameters'

    DE1_READ_ONCE = 'de1/read_once_values'

    DE1_PRESENCE = 'de1/presence'

    SCALE = 'scale'

    SCALE_ID = 'scale/id'

    SCALE_TARE = 'scale/tare'
    SCALE_DISPLAY = 'scale/display'

    SCALE_AVAILABILITY = 'scale/availability'
    SCALE_CONNECTIVITY = 'scale/connectivity'

    FLOW_SEQUENCER = 'flow_sequencer'
    FLOW_SEQUENCER_SETTING = 'flow_sequencer/settings'
    FLOW_SEQUENCER_PARAMETER_SET = 'flow_sequencer/parameter_set'

    VERSION = 'version'

    @property
    def can_get(self):
        retval = True

        # is FALSE
        if self in (
                self.SCAN,
                self.DE1_MODE,
                self.SCALE_TARE,
                self.SCALE_DISPLAY,
                # unimplemented
                self.DE1_PROFILE,
                self.DE1_PROFILE_STORE,
                self.DE1_PROFILES,
                self.DE1_FIRMWARE,
                self.DE1_FIRMWARES,
                self.DE1_DEPRECATED,
        ):
            retval = False

        return retval

    @property
    def can_put(self):
        retval = True

        # is FALSE
        if self in (
                self.SCAN_DEVICES,
                self.DE1_READ_ONCE,
                self.VERSION,
                self.LOG,
                self.LOGS,
                self.DE1_STATE,
                self.DE1_PROFILES,
                self.DE1_FIRMWARES,
                # unimplemented
                self.DE1_DEPRECATED,
        ):
            retval = False

        return retval

    @property
    def can_patch(self):
        retval = self.can_put
        # Can't PATCH firmware or profiles, have to PUT

        # is FALSE
        if self in (
                self.DE1_FIRMWARE,
                self.DE1_FIRMWARE_ID,
                self.DE1_PROFILE,
                self.DE1_PROFILE_ID,
                self.DE1_PROFILE_STORE,
        ):
            retval = False

        return retval

    @property
    def can_post(self):
        retval = False
        # No POST implemented
        return retval

    @property
    def can_delete(self):
        retval = False
        # No DELETE implemented
        return retval


class ConnectivityEnum (enum.Enum):

    NOT_CONNECTED = 'not_connected'
    CONNECTED = 'connected'
    READY = 'ready'


class DE1ModeEnum (enum.Enum):

    SLEEP = 'Sleep'
    WAKE = 'Wake'
    STOP = 'Stop'
    END_STEAM = 'EndSteam'
    # TODO: Determine conditions under which these can be activated
    #       For now, assume the machine needs to be in Idle
    CLEAN = 'Clean'
    DESCALE = 'Descale'
    TRANSPORT = 'Transport' # AirPurge

    # Maybe sending NoRequest will trigger a report?
    NO_REQUEST = 'NoRequest'

    # Only valid during espresso flow
    SKIP_TO_NEXT = 'SkipToNext'

    # Only valid for non-GHC machines
    ESPRESSO = 'Espresso'
    STEAM = 'Steam'
    HOT_WATER = 'HotWater'
    HOT_WATER_RINSE = 'HotWaterRinse'

