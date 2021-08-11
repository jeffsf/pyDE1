"""
Used by FlowSequencer

Declared separately to make flow_sequencer.py easier to read
as they need to be "forward declared"
"""
import logging
from typing import Optional

from pyDE1.exceptions import DE1APIError, DE1APITypeError, DE1APIValueError

logger = logging.getLogger('FlowSequencer')

# These apply to Espresso only, at this time. Others return 0
LAST_DROPS_MINIMUM_TIME_DEFAULT = 3.0  # seconds
# Allow a grace period after flow begins during which scale continues to tare.
# 1 or 2 bar OK for slower-flowing profiles. "Turbo" shots 0, or maybe 1 bar.
FIRST_DROPS_THRESHOLD_DEFAULT = 0.0  # bar

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
                logger.info("Deprecated use of 0 for stop-at replaced by None")
            elif value < 0:
                raise DE1APIValueError(
                    f"Stop-at values need to be non-negative ({value})"
                )
        return value


class StopAtTime (ByModeControl):

    def __init__(self, stop_at_time: Optional[float] = None):
        # Mix-in, call super from concrete instance
        self._stop_at_time = None
        self.stop_at_time = stop_at_time

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


class EspressoControl (StopAtTime, StopAtVolume, StopAtWeight, ByModeControl):

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
        self._profile_can_override_stop_limits = True
        self._profile_can_override_tank_temperature = True
        self._first_drops_threshold = None
        ByModeControl.__init__(self, disable_auto_tare=disable_auto_tare)
        StopAtTime.__init__(self, stop_at_time=stop_at_time)
        StopAtVolume.__init__(self, stop_at_volume=stop_at_volume)
        StopAtWeight.__init__(self, stop_at_weight=stop_at_weight)
        self._profile_can_override_stop_limits \
            = profile_can_override_stop_limits
        self._profile_can_override_tank_temperature \
            = profile_can_override_tank_temperature
        self.first_drops_threshold = first_drops_threshold
        self.last_drops_minimum_time = last_drops_minimum_time

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


class SteamControl (ByModeControl):

        def __init__(self, disable_auto_tare: bool = True):
            super(SteamControl, self).__init__(
                disable_auto_tare=disable_auto_tare)

        @property
        def stop_at_time(self):
            # This allows a try/except catch in FlowSequencer
            # as stop_at_time is implemented, but not here
            raise DE1APIError(
                "Steam time is set by the DE1, not SteamControl.stop_at_time"
            )


class HotWaterControl (StopAtWeight, ByModeControl):

    def __init__(self, disable_auto_tare: bool = True,
                 stop_at_weight: Optional[float] = None,
                 ):
        ByModeControl.__init__(self,
                               disable_auto_tare=disable_auto_tare)
        StopAtWeight.__init__(self, stop_at_weight=stop_at_weight)


class HotWaterRinseControl (StopAtTime, ByModeControl):

    def __init__(self, disable_auto_tare: bool = True,
                 stop_at_time: Optional[float] = None,
                 ):
        ByModeControl.__init__(self,
                               disable_auto_tare=disable_auto_tare)
        StopAtTime.__init__(self, stop_at_time=stop_at_time)
