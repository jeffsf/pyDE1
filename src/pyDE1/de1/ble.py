"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum

from pyDE1.exceptions import DE1APIError


class CUUID (enum.Enum):
    """
    Maps the various C API objects to their corresponding BLE CUUIDs.

    A CUUID itself should be sufficient as a parameter in most cases.
    When needing the full UUID string, use CUUID.uuid

    A lock is provided, associated with each CUUID in case exclusive access
    is found to be needed. It is presently used by
    de1.write_packed_attr_return_notification()
    """
    Versions =          "a001"  # read,        notify
    RequestedState =    "a002"  # read, write, notify
    SetTime =           "a003"  # read, write, notify
    ShotDirectory =     "a004"  # read, write, notify
    ReadFromMMR =       "a005"  # read, write, notify
    WriteToMMR =        "a006"  #       write, notify
    ShotMapRequest =    "a007"  #       write, notify
    DeleteShotRange =   "a008"  #       write, notify
    FWMapRequest =      "a009"  #       write, notify
    Temperatures =      "a00a"  # read,        notify
    ShotSettings =      "a00b"  # read, write, notify
    Deprecated =        "a00c"  # read, write, notify
    ShotSample =        "a00d"  # read,        notify
    StateInfo =         "a00e"  # read,        notify
    HeaderWrite =       "a00f"  # read, write, notify
    FrameWrite =        "a010"  # read, write, notify
    WaterLevels =       "a011"  # read, write, notify
    Calibration =       "a012"  # read, write, notify

    def __init__(self, value):
        # super(CUUID, self).__init__(value)
        #     NameError: name 'CUUID' is not defined
        enum.Enum.__init__(value)
        # TODO: Confirm that locking by CUUID is sufficient
        # TODO: Decide if locking the "profile" is sufficient
        self._lock = asyncio.Lock()

    @property
    def can_read(self) -> bool:
        """
        Hard-coded test of the CUUID supports read.

        Does not take into account if the DE! is connected or not.

        The ReadFromMMR requests are in words, not bytes
        They are not properly recognized at this time by ReadFromMMR_callback
        For now, declare as not readable
        """
        return not (self in (CUUID.ReadFromMMR,
                             #
                             CUUID.WriteToMMR,
                             CUUID.ShotMapRequest,
                             CUUID.DeleteShotRange,
                             CUUID.FWMapRequest,
                             )
                    )

    @property
    def can_write(self) -> bool:
        """
        Hard-coded test of the CUUID supports write.

        Does not take into account if the DE! is connected or not.
        """
        return not (self in (CUUID.Versions,
                             CUUID.Temperatures,
                             CUUID.ShotSample,
                             CUUID.StateInfo,
                             )
                    )

    @property
    def can_notify(self) -> bool:
        """
        Hard-coded test of the CUUID supports notify.

        All are listed as notifying, though some do not return anything.

        Does not take into account if the DE! is connected or not.
        """
        return True

    # Very conservative right now
    # Even if a notify comes, if the command is "bad"
    # nothing may ever come back
    # Not FrameWrite as it does not notify on write
    @property
    def can_write_then_return(self) -> bool:
        """
        Hard-coded test of the CUUID supports write and will then notify.

        "Unrecognized" commands written may not result in a response,
        so waiting on a response may "hang" as a result.

        Does not take into account if the DE1 is connected or not.
        """
        return self in (
            CUUID.FWMapRequest,
            CUUID.Calibration,
        )

    @property
    def uuid(self) -> str:
        return f"0000{self.value}-0000-1000-8000-00805f9b34fb"

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def is_read_once(self):
        """
        Those that don't change with time (except at reboot)
        """
        return self is self.Versions

    @property
    def is_stable(self):
        """
        Those that don't change without being written
        """
        return self.is_read_once or self is self.Calibration


class UnsupportedBLEActionError(DE1APIError):
    def __init__(self, *args, **kwargs):
        super(UnsupportedBLEActionError, self).__init__(args, kwargs)