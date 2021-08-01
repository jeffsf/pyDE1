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

from pyDE1.event_manager import EventPayload


class ConnectivityState (enum.Enum):
    UNKNOWN = 'unknown'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    READY = 'ready'  # "Ready for use"
    NOT_READY = 'not_ready'  # Was READY, but is no longer
    DISCONNECTING = 'disconnecting'
    DISCONNECTED = 'disconnected'


class ConnectivityChange (EventPayload):

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
