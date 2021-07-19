"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Common events for the DE1 itself
"""

from copy import copy
from typing import Optional, List

from pyDE1.event_manager import EventPayload
from pyDE1.de1.c_api import API_MachineStates, API_Substates


class StateUpdate (EventPayload):
    """
    Derived from StateInfo

    Track previous centrally as it seems needed by so many consumers
    Tracking "at the source" should also be more robust

    No previous information is represented as NoRequest,NoState
    """
    def __init__(self, arrival_time: float,
                 state: API_MachineStates,
                 substate: API_Substates,
                 previous_state: Optional[API_MachineStates]=None,
                 previous_substate: Optional[API_Substates]=None,
                 ):
        super(StateUpdate, self).__init__(arrival_time=arrival_time)
        self._version = "1.0.0"  # Major version incremented on breaking change
        self.state = state
        self.substate = substate
        if previous_state is None:
            previous_state = API_MachineStates.NoRequest
        if previous_substate is None:
            previous_substate = API_Substates.NoState
        self.previous_state = previous_state
        self.previous_substate = previous_substate
        # External consumers don't have API_Substates.is_error
        self.is_error_state = (
                self.state == API_MachineStates.FatalError
                or self.substate.is_error
        )


class ShotSampleUpdate (EventPayload):
    """
    Derived from ShotSample

    See ShotSampleWithVolumeUpdates for API-visible class
    """
    _internal_only = True

    def __init__(self, arrival_time: float,
                 sample_time: int,
                 group_pressure: float,
                 group_flow: float,
                 mix_temp: float,
                 head_temp: float,
                 set_mix_temp: float,
                 set_head_temp: float,
                 set_group_pressure: float,
                 set_group_flow: float,
                 frame_number: int,
                 steam_temp: float,
                 ):
        super(ShotSampleUpdate, self).__init__(arrival_time=arrival_time)
        # TODO: This will need to be managed carefully as impacts subclass
        self._version = "1.2.0"  # Major version incremented on breaking change
        self.sample_time = sample_time
        self.group_pressure = group_pressure
        self.group_flow = group_flow
        self.mix_temp = mix_temp
        self.head_temp = head_temp
        self.set_mix_temp = set_mix_temp
        self.set_head_temp = set_head_temp
        self.set_group_pressure = set_group_pressure
        self.set_group_flow = set_group_flow
        self.frame_number = frame_number
        self.steam_temp = steam_temp


class WaterLevelUpdate (EventPayload):
    """
    Derived from WaterLevels
    """
    def __init__(self, arrival_time:float,
                 level: float, start_fill_level:float):
        super(WaterLevelUpdate, self).__init__(arrival_time)
        self._version = "1.0.0"  # Major version incremented on breaking change
        self.level = level
        self.start_fill_level = start_fill_level


class ShotSampleWithVolumesUpdate (ShotSampleUpdate):
    """
    Delivered after ShotSampleUpdate,
    includes calculated then tracked volumes

    de1_time is preferred as it may eventually be time-base adjusted
    """
    _internal_only = False

    def __init__(self, shot_sample_update: ShotSampleUpdate,
                 volume_preinfuse: float,
                 volume_pour: float,
                 volume_total: float,
                 volume_by_frame: List[float],
                 ):
        # TODO: Is there a better way to do this?
        super(ShotSampleWithVolumesUpdate, self).__init__(
            arrival_time=shot_sample_update.arrival_time,
            sample_time=shot_sample_update.sample_time,
            group_pressure=shot_sample_update.group_pressure,
            group_flow=shot_sample_update.group_flow,
            mix_temp=shot_sample_update.mix_temp,
            head_temp=shot_sample_update.head_temp,
            set_mix_temp=shot_sample_update.set_mix_temp,
            set_head_temp=shot_sample_update.set_head_temp,
            set_group_pressure=shot_sample_update.set_group_pressure,
            set_group_flow=shot_sample_update.set_group_flow,
            frame_number=shot_sample_update.frame_number,
            steam_temp=shot_sample_update.steam_temp,
        )
        # TODO: This will need to be managed carefully as depends on super
        self._version = "1.2.0"  # Major version incremented on breaking change

        self.de1_time = self.arrival_time
        self.volume_preinfuse = volume_preinfuse
        self.volume_pour = volume_pour
        self.volume_total = volume_total
        self.volume_by_frames = copy(volume_by_frame)
