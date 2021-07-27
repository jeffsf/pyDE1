"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Enum that defines the recognized resources that the Dispatcher can access
"""

import enum

RESOURCE_VERSION = '3.0.0'


class Resource (enum.Enum):

    SCAN = 'scan'
    SCAN_DEVICES = 'scan/devices'

    LOG = 'log/{id}'  # TODO: OK, how to I match this?
    LOGS = 'logs'

    DE1 = 'de1'

    DE1_ID = 'de1/id'

    DE1_MODE = 'de1/mode'

    DE1_PROFILE = 'de1/profile'
    DE1_PROFILE_ID = 'de1/profile/id'
    DE1_PROFILES = 'de1/profiles'

    DE1_FIRMWARE = 'de1/firmware'
    DE1_FIRMWARE_ID = 'de1/firmware/id'
    DE1_FIRMWARES = 'de1/firmwares'

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

    DE1_SETTING_STEAM = 'de1/setting/steam'

    DE1_DEPRECATED = 'de1/setting/tbd_name_other_shot_settings'
    DE1_SETTING_TIME = 'de1/setting/time'

    DE1_CALIBRATION = 'de1/calibration'
    DE1_CALIBRATION_LINE_FREQUENCY = 'de1/calibration/line_frequency'
    DE1_CALIBRATION_FLOW_MULTIPLIER = 'de1/calibration/flow_multiplier'
    DE1_CALIBRATION_INTERNAL = 'de1/calibration/internal'

    DE1_PARAMETER_SET = 'de1/parameters'

    DE1_READ_ONCE = 'de1/read_once_values'

    SCALE = 'scale'

    SCALE_ID = 'scale/id'

    SCALE_TARE = 'scale/tare'
    SCALE_DISPLAY = 'scale/display'

    SCALE_CONNECTIVITY = 'scale/connectivity'

    FLOW_SEQUENCER = 'flow_sequencer'
    FLOW_SEQUENCER_SETTING = 'flow_sequencer/settings'
    FLOW_SEQUENCER_PARAMETER_SET = 'flow_sequencer/parameter_set'

    VERSION = 'version'

    @property
    def can_get(self):
        retval = True
        # False if in
        if self in (
                self.SCAN,
                self.DE1_MODE,
                self.SCALE_TARE,
                self.SCALE_DISPLAY,
                # unimplemented
                self.DE1_PROFILE,
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
        # False if in
        if self in (
                self.SCAN_DEVICES,
                self.DE1_READ_ONCE,
                self.VERSION,
                self.LOG,
                self.LOGS,
                self.DE1_PROFILES,
                self.DE1_FIRMWARES,
                # unimplemented
                self.DE1_FIRMWARE,
                self.DE1_DEPRECATED,
        ):
            retval = False
        return retval

    @property
    def can_patch(self):
        retval = self.can_put
        # Can't PATCH firmware or profiles, have to PUT
        # False if in
        if self in (
                self.DE1_FIRMWARE,
                self.DE1_FIRMWARE_ID,
                self.DE1_PROFILE,
                self.DE1_PROFILE_ID,
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
        return self.can_post


class ConnectivityEnum (enum.Enum):

    NOT_CONNECTED = 'not_connected'
    CONNECTED = 'connected'
    READY = 'ready'


class DE1ModeEnum (enum.Enum):

    SLEEP = 'Sleep'
    WAKE = 'Wake'
    STOP = 'Stop'
    # TODO: Determine conditions under which these can be activated
    # CLEAN = 'Clean'
    # DESCALE = 'Descale'
    # TRANSPORT = 'Transport' # AirPurge

    # Only valid during espresso flow
    SKIP_TO_NEXT = 'SkipToNext'

    # Only valid for non-GHC machines
    ESPRESSO = 'Espresso'
    STEAM = 'Steam'
    HOT_WATER = 'HotWater'
    HOT_WATER_RINSE = 'HotWaterRinse'
