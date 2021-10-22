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
from typing import Optional

import pyDE1
from pyDE1.de1.c_api import API_MachineStates
from pyDE1.event_manager.payloads import EventPayload
from pyDE1.exceptions import (
    DE1APITypeError, DE1APIValueError, DE1APINotManagedHereException
)


logger = pyDE1.getLogger('FlowSequencer')


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
                                 state: API_MachineStates) -> 'ByModeControl':
        raise NotImplementedError

    @property
    def active_control(self) -> 'ByModeControl':
        raise NotImplementedError

    @property
    def sequence_start_time(self):
        raise NotImplementedError

    async def stop_at_notify(self, stop_at: 'StopAtType',
                             action: 'StopAtNotificationAction',
                             current: Optional[float] = None):
        raise NotImplementedError

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
                 active_state: API_MachineStates = API_MachineStates.NoRequest):
        now = time.time()
        super(StopAtNotification, self).__init__(
            arrival_time=now,
            create_time=now
        )
        self._version = "1.0.0"
        self.stop_at = stop_at
        self.action = action
        self.target_value = target_value
        self.current_value = current_value
        self.active_state = active_state


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


class ByModeControl:
    """
    Generic holder for stop-at values and other "in-the-moment" parameters
    that are related to flow sequence

    As stop-at-time is handled for steam by the DE1 and that is an async call
    will have to figure out how to manage that at this level. The API already
    directs to the DE1.

    stop_at_time: Steam (DE1), HotWaterRinse, Espresso desirable to add
    stop_at_volume: Espresso, HotWater
    stop_at_weight: Espresso, HotWater
    disable_auto_tare: All

    specials: Espresso only
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

    @property
    def stop_at_time(self):
        return None

    @property
    def stop_at_weight(self):
        return None

    @property
    def stop_at_volume(self):
        return None

    @property
    def last_drops_minimum_time(self):
        return 0

    @property
    def first_drops_threshold(self):
        return 0

    # Validate these, as they will be coming from the API
    # The API should have already done type validation
    # Though not used by the base class, lowers repetition

    @staticmethod
    def _validate_stop_at(value):
        if value is not None:
            if value == 0:
                value = None
                logger.info(
                    "Deprecated use of 0 for stop-at, replaced by None")
            elif value < 0:
                raise DE1APIValueError(
                    f"Stop-at values need to be non-negative ({value})")
        return value


class StopAtTime (ByModeControl):

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
        self._stop_at_time = self._validate_stop_at(value)


class StopAtVolume (ByModeControl):

    def __init__(self, stop_at_volume: Optional[float] = None):
        # Mix-in, call super from concrete instance
        self._stop_at_volume = None
        self.stop_at_volume = stop_at_volume

    @property
    def stop_at_volume(self):
        return self._stop_at_volume

    @stop_at_volume.setter
    def stop_at_volume(self, value):
        self._stop_at_volume = self._validate_stop_at(value)


class StopAtWeight (ByModeControl):

    def __init__(self, stop_at_weight: Optional[float] = None):
        # Mix-in, call super from concrete instance
        self._stop_at_weight = None
        self.stop_at_weight = stop_at_weight

    @property
    def stop_at_weight(self):
        return self._stop_at_weight

    @stop_at_weight.setter
    def stop_at_weight(self, value):
        self._stop_at_weight = self._validate_stop_at(value)

# Create importable for mode-specific control classes?
# No, just import locally, if needed, from flow_sequencer_impl
