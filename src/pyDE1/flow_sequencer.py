"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only


FlowSequencer knows about the DE1 and imports it
DE1 needs to know about the FlowSequencer to be able to set stop-at targets.

Resolve by defining a restricted interface
"""
import enum
import multiprocessing
import time
from typing import Optional, Union

import pyDE1
from pyDE1.de1.c_api import API_MachineStates, MAX_FRAMES
from pyDE1.event_manager.payloads import EventPayload
from pyDE1.exceptions import (
    DE1APITypeError, DE1APIValueError, DE1APINotManagedHereException
)


logger = pyDE1.getLogger('FlowSequencer')

ModeControl = Union[
    'I_EspressoControl',
    'I_HotWaterControl',
    'I_HotWaterRinseControl',
    'I_SteamControl'
]


class FlowSequencer():
    """
    A singleton base class that helps break circular includes
    Returns the FlowSequencerImpl singleton
    """

    def __new__(cls, *args, **kwds):
        # By importing FlowSequencerImpl at run time,
        # potential import issues should be mitigated.
        import pyDE1.flow_sequencer_impl
        return pyDE1.flow_sequencer_impl.FlowSequencerImpl()

    database_queue: Optional[multiprocessing.Queue] = None
    
    @property
    def stop_at_weight_adjust(self):
        raise NotImplementedError

    @property
    def de1(self):
        raise NotImplementedError

    async def set_up_subscribers(self):
        raise NotImplementedError

    @property
    def scale_processor(self):
        raise NotImplementedError

    @property
    def active_state(self):
        raise NotImplementedError

    def active_control_for_state(self,
                                 state: API_MachineStates) -> ModeControl:
        raise NotImplementedError

    @property
    def active_control(self) -> ModeControl:
        raise NotImplementedError

    @property
    def sequence_start_time(self):
        raise NotImplementedError

    # async def stop_at_notify(self, stop_at: 'StopAtType',
    #                          action: 'StopAtNotificationAction',
    #                          target_value: Optional[float],
    #                          current_value: Optional[float],
    #                          active_state: API_MachineStates,
    #                          current_frame: Optional[int]):
    #     raise NotImplementedError

    def stop_at_time_set(self, state: API_MachineStates, duration: float):
        raise NotImplementedError

    def stop_at_volume_set(self, state: API_MachineStates, volume: float):
        raise NotImplementedError

    def stop_at_weight_set(self, state: API_MachineStates, weight: float):
        raise NotImplementedError

    def profile_can_override_stop_limits(self, state: API_MachineStates):
        raise NotImplementedError

    def profile_can_override_tank_temperature(self, state: API_MachineStates):
        raise NotImplementedError

    async def on_de1_nearly_ready(self) -> None:
        raise NotImplementedError


LAST_DROPS_MINIMUM_TIME_DEFAULT = 3.0  # seconds
FIRST_DROPS_THRESHOLD_DEFAULT = 0.0  # bar


class StopAtNotificationAction (enum.Enum):
    ENABLED = 'enabled'
    TRIGGERED = 'triggered'
    DISABLED = 'disabled'
    DE1CONTROLLED = 'de1 controlled'


class StopAtType (enum.Enum):
    TIME = 'time'
    VOLUME = 'volume'
    WEIGHT = 'weight'
    MOW  = 'move on by weight'


class StopAtNotification (EventPayload):
    """
    Enable, disable, trigger of the various stop-at conditions
    current_value is generally only set for StopAtNotificationAction.TRIGGERED

    ENABLED notifications are given even if the target is None as the target
    can be changed during the shot, at least when managed by the FlowSequencer
    (On-the-fly profile changes are not supported at this time.
     On-the-fly changes to steam duration have not been tested at this time.)
    """
    def __init__(self, stop_at: StopAtType,
                 action: StopAtNotificationAction,
                 target_value: Optional[float] = None,
                 current_value: Optional[float] = None,
                 active_state: API_MachineStates = API_MachineStates.NoRequest,
                 current_frame: Optional[int] = None):
        now = time.time()
        super(StopAtNotification, self).__init__(
            arrival_time=now,
            create_time=now
        )
        self._version = "1.1.0"
        self.stop_at = stop_at
        self.action = action
        self.target_value = target_value
        self.current_value = current_value
        self.active_state = active_state
        self.current_frame = current_frame


class AutoTareNotificationAction (enum.Enum):
    ENABLED = 'enabled'
    DISABLED = 'disabled'


class AutoTareNotification (EventPayload):

    def __init__(self, action: AutoTareNotificationAction):
        now = time.time()
        super(AutoTareNotification, self).__init__(
            arrival_time=now,
            create_time=now
        )
        self._version = "1.0.0"
        self.action = action


class BaseModeControl:
    """
    Generic holder for parameters common to all four ModeControl objects,
    Espresso, HotWater, HotWaterFlush, and Steam
    """

    def __init__(self, disable_auto_tare: bool = False):
        self._disable_auto_tare = None
        self.disable_auto_tare = disable_auto_tare

    @property
    def disable_auto_tare(self):
        return self._disable_auto_tare

    @disable_auto_tare.setter
    def disable_auto_tare(self, value):
        if not isinstance(value, bool):
            raise DE1APITypeError(
                f"disable_auto_tare must be a bool, not {value}"
            )
        self._disable_auto_tare = value


def validate_stop_at(value):
    if value is not None:
        if value == 0:
            value = None
            logger.info(
                "Deprecated use of 0 for stop-at or move-on, "
                "replaced by None")
        elif value < 0:
            raise DE1APIValueError(
                "Stop-at and move-on values need to be non-negative, "
                f"not '{value}'")
    return value


class StopAtTimeControl:

    def __init__(self, stop_at_time: Optional[float] = None):
        # Mix-in, call super from concrete instance
        self._stop_at_time = None
        try:
            self.stop_at_time = stop_at_time
        except DE1APINotManagedHereException:
            self._stop_at_time = stop_at_time

    @property
    def stop_at_time(self):
        return self._stop_at_time

    @stop_at_time.setter
    def stop_at_time(self, value):
        self._stop_at_time = validate_stop_at(value)


class StopAtVolumeControl:

    def __init__(self, stop_at_volume: Optional[float] = None):
        # Mix-in, call super from concrete instance
        self._stop_at_volume = None
        self.stop_at_volume = stop_at_volume

    @property
    def stop_at_volume(self):
        return self._stop_at_volume

    @stop_at_volume.setter
    def stop_at_volume(self, value):
        self._stop_at_volume = validate_stop_at(value)


class StopAtWeightControl:

    def __init__(self, stop_at_weight: Optional[float] = None):
        # Mix-in, call super from concrete instance
        self._stop_at_weight = None
        self.stop_at_weight = stop_at_weight

    @property
    def stop_at_weight(self):
        return self._stop_at_weight

    @stop_at_weight.setter
    def stop_at_weight(self, value):
        self._stop_at_weight = validate_stop_at(value)


class MoveOnWeightControl:

    def __init__(self, mow_all_frames: Optional[list[Optional[float]]] = None):
        # Mix-in, call super from concrete instance
        self._mow_all_frames = []
        self.mow_all_frames = mow_all_frames

    @property
    def mow_all_frames(self) -> list[Optional[Union[int, float]]]:
        return self._mow_all_frames.copy()

    @mow_all_frames.setter
    def mow_all_frames(self,
                       value_list: Optional[list[Optional[Union[int, float]]]]):
        if value_list is None:
            value_list = []
        if not isinstance(value_list, list):
            raise DE1APIValueError(
                f"Move-on-weight setter expecting a list, not '{value_list}'")
        if len(value_list):
            map(validate_stop_at, value_list)
        self._mow_all_frames = value_list

    def mow_get_frame(self, frame_number: int) -> Optional[Union[int, float]]:
        retval = None
        if frame_number is not None:
            try:
                retval = self._mow_all_frames[frame_number]
            except IndexError:
                pass
        return retval

    def mow_set_frame(self, frame_number: int,
                      value: Optional[Union[int, float]]):
        if frame_number > MAX_FRAMES:
            raise DE1APIValueError(
                f"Request to set mow for frame {frame_number} > MAX_FRAMES")
        if frame_number is None:
            raise DE1APIValueError(
                f"Request to set mow for frame 'None'")
        if frame_number < 0:
            raise DE1APIValueError(
                f"Request to set mow for frame {frame_number} < 0")
        validate_stop_at(value)
        while len(self._mow_all_frames) < frame_number:
            self._mow_all_frames.append(None)
        self._mow_all_frames[frame_number] = value


class ProfileOverrideControl:

    def __init__(self,
                 profile_can_override_stop_limits: bool = True,
                 profile_can_override_tank_temperature: bool = True,
                 ):
        self._profile_can_override_stop_limits \
            = profile_can_override_stop_limits
        self._profile_can_override_tank_temperature \
            = profile_can_override_tank_temperature

    @property
    def profile_can_override_stop_limits(self):
        return self._profile_can_override_stop_limits

    @profile_can_override_stop_limits.setter
    def profile_can_override_stop_limits(self, value):
        if not isinstance(value, bool):
            raise DE1APITypeError(
                "profile_can_override_stop_limits must be a bool, "
                f"not {value}"
            )
        self._profile_can_override_stop_limits = value

    @property
    def profile_can_override_tank_temperature(self):
        return self._profile_can_override_tank_temperature

    @profile_can_override_tank_temperature.setter
    def profile_can_override_tank_temperature(self, value):
        if not isinstance(value, bool):
            raise DE1APITypeError(
                "profile_can_override_tank_temperature must be a bool, "
                f"not {value}"
            )
        self._profile_can_override_tank_temperature = value


class EspressoDropsControl:

    def __init__(self,
                 first_drops_threshold: Optional[float] = \
                         FIRST_DROPS_THRESHOLD_DEFAULT,
                 last_drops_minimum_time: float = \
                         LAST_DROPS_MINIMUM_TIME_DEFAULT,
                 ):
        self.first_drops_threshold = first_drops_threshold
        self.last_drops_minimum_time = last_drops_minimum_time

    @property
    def first_drops_threshold(self):
        return self._first_drops_threshold

    @first_drops_threshold.setter
    def first_drops_threshold(self, value):
        if value and not (0 <= value <= 10):
            raise DE1APIValueError(
                f"first_drops_threshold not 0 <= {value} <= 10")
        self._first_drops_threshold = value

    @property
    def last_drops_minimum_time(self):
        return self._last_drops_minimum_time

    @last_drops_minimum_time.setter
    def last_drops_minimum_time(self, value):
        if value < 0:
            raise DE1APIValueError(
                f"last_drops_minimum_time less than zero ({value}")
        self._last_drops_minimum_time = value


# These are primarily defined here as interfaces and some "real" implementation
# details in flow_sequencer_impl.py to break circular dependencies
# between the DE1 and FlowSequencer definitions.

class I_EspressoControl (BaseModeControl,
                         StopAtTimeControl,
                         StopAtVolumeControl,
                         StopAtWeightControl,
                         MoveOnWeightControl,
                         EspressoDropsControl,
                         ProfileOverrideControl):

    def __init__(self, disable_auto_tare: bool = False,
                 stop_at_time: Optional[float] = None,
                 stop_at_volume: Optional[float] = None,
                 stop_at_weight: Optional[float] = None,
                 profile_can_override_stop_limits: bool = True,
                 profile_can_override_tank_temperature: bool = True,
                 first_drops_threshold: Optional[float] = \
                         FIRST_DROPS_THRESHOLD_DEFAULT,
                 last_drops_minimum_time: float = \
                         LAST_DROPS_MINIMUM_TIME_DEFAULT,
                 ):
        BaseModeControl.__init__(self, disable_auto_tare=disable_auto_tare)
        StopAtTimeControl.__init__(self, stop_at_time=stop_at_time)
        StopAtVolumeControl.__init__(self, stop_at_volume=stop_at_volume)
        StopAtWeightControl.__init__(self, stop_at_weight=stop_at_weight)
        # As the control is usually instantiated before a DE1 is connected
        # and before a profile is uploaded, the default here is OK
        MoveOnWeightControl.__init__(self, mow_all_frames=None)
        EspressoDropsControl.__init__(self,
                            first_drops_threshold=first_drops_threshold,
                            last_drops_minimum_time=last_drops_minimum_time)
        ProfileOverrideControl.__init__(self,
                            profile_can_override_stop_limits= \
                                profile_can_override_stop_limits,
                            profile_can_override_tank_temperature= \
                                profile_can_override_tank_temperature)


class I_HotWaterControl (BaseModeControl,
                         StopAtTimeControl,
                         StopAtVolumeControl,
                         StopAtWeightControl):

    def __init__(self, disable_auto_tare: bool = False,
                 stop_at_time: Optional[float] = None,
                 stop_at_volume: Optional[float] = None,
                 stop_at_weight: Optional[float] = None,
                 ):
        BaseModeControl.__init__(self, disable_auto_tare=disable_auto_tare)
        StopAtTimeControl.__init__(self, stop_at_time=stop_at_time)
        StopAtVolumeControl.__init__(self, stop_at_volume=stop_at_volume)
        StopAtWeightControl.__init__(self, stop_at_weight=stop_at_weight)


class I_HotWaterRinseControl (BaseModeControl,
                              StopAtTimeControl,
                              ):

    def __init__(self, disable_auto_tare: bool = False,
                 stop_at_time: Optional[float] = None,
                 ):
        BaseModeControl.__init__(self, disable_auto_tare=disable_auto_tare)
        StopAtTimeControl.__init__(self, stop_at_time=stop_at_time)

    # stop_at_time overridden by HotWaterRinseControl


class I_SteamControl (BaseModeControl,
                      StopAtTimeControl,
                      ):

    def __init__(self, disable_auto_tare: bool = False,
                 stop_at_time: Optional[float] = None,
                 ):
        BaseModeControl.__init__(self, disable_auto_tare=disable_auto_tare)
        StopAtTimeControl.__init__(self, stop_at_time=stop_at_time)

    # stop_at_time overridden by SteamControl
