"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Events that are shared across multiple classes

See also:
    EventWithNotify that wraps asyncio.Event()
    async def send_to_outbound_queue(payload: EventPayload)
"""

import enum
from typing import Optional

from pyDE1.event_manager.payloads import EventPayload


class DeviceRole (enum.Enum):
    DE1 = 'de1'
    SCALE = 'scale'
    THERMOMETER = 'thermometer'
    OTHER = 'other'
    UNKNOWN = 'unknown'


class ConnectivityState (enum.Enum):
    # NB: Will deprecate in favor of DeviceAvailability
    INITIAL = 'initial'
    UNKNOWN = 'unknown'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    READY = 'ready'  # "Ready for use"
    NOT_READY = 'not_ready'  # Was READY, but is no longer
    DISCONNECTING = 'disconnecting'
    DISCONNECTED = 'disconnected'


class ConnectivityChange (EventPayload):
    # NB: Will deprecate in favor of DeviceAvailability
    def __init__(self,
                 arrival_time: float,
                 state: ConnectivityState = ConnectivityState.UNKNOWN,
                 id: Optional[str] = None,
                 name: Optional[str] = None,
                 ):
        super(ConnectivityChange, self).__init__(arrival_time=arrival_time)
        self._version = "1.1.0"
        self.state = state
        self.id = id
        self.name = name


class DeviceAvailabilityState (enum.Enum):
    INITIAL = 'initial'
    UNKNOWN = 'unknown'
    CAPTURING = 'capturing'
    CAPTURED = 'captured'
    READY = 'ready'  # "Ready for use"
    NOT_READY = 'not ready'  # Was READY, but is no longer
    RELEASING = 'releasing'
    RELEASED = 'released'


class DeviceAvailability (EventPayload):
    def __init__(self,
                 arrival_time: float,
                 state: DeviceAvailabilityState \
                         = DeviceAvailabilityState.UNKNOWN,
                 role: DeviceRole = DeviceRole.UNKNOWN,
                 id: Optional[str] = None,
                 name: Optional[str] = None,
                 ):
        super(DeviceAvailability, self).__init__(arrival_time=arrival_time)
        self._version = "1.1.0"
        self.state = state
        self.role = role
        self.id = id
        self.name = name


class FirmwareUploadState (enum.Enum):
    STARTING = 'starting'
    UPLOADING = 'uploading'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELED = 'canceled'


class FirmwareUpload (EventPayload):

    def __init__(self,
                 arrival_time: float,
                 state: FirmwareUploadState,
                 uploaded: Optional[int] = None,
                 total: Optional[int] = None,
                 ):
        super(FirmwareUpload, self).__init__(arrival_time=arrival_time)
        self._version = "1.0.0"
        self.state = state
        self.uploaded = uploaded
        self.total = total
