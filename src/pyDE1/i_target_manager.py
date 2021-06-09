"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only


FlowSequencer knows about the DE1 and imports it
DE1 needs to know about the FlowSequencer to be able to set stop-at targets.

Resolve by defining a restricted interface
"""

from typing import Optional

from pyDE1.de1.c_api import API_MachineStates

class I_TargetManager:

    def stop_at_weight(self, state: Optional[API_MachineStates] = None) \
            -> Optional[float]:
        raise NotImplementedError

    def stop_at_volume(self, state: Optional[API_MachineStates] = None) \
            -> Optional[float]:
        raise NotImplementedError

    def stop_at_time(self, state: Optional[API_MachineStates] = None) \
            -> Optional[float]:
        raise NotImplementedError

    def stop_at_weight_set(self, state: API_MachineStates, weight: float):
        raise NotImplementedError

    def stop_at_volume_set(self, state: API_MachineStates, volume: float):
        raise NotImplementedError

    def stop_at_time_set(self, state: API_MachineStates, duration: float):
        raise NotImplementedError