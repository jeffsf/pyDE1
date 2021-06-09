"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Common events for scales
"""

from pyDE1.event_manager import EventPayload


class ScaleWeightUpdate(EventPayload):
    """
    See WeightAndFlowUpdate for API-visible class
    """
    _internal_only = True

    def __init__(self,
                 arrival_time: float,
                 scale_time: float,
                 weight: float, ):
        super(ScaleWeightUpdate, self).__init__(arrival_time=arrival_time)
        self._version = "1.0.0"
        self.scale_time = scale_time
        self.weight = weight


class ScaleButtonPress(EventPayload):

    def __init__(self, arrival_time: float, button: int):
        super(ScaleButtonPress, self).__init__(arrival_time=arrival_time)
        self._version = "1.0.0"  # Major version incremented on breaking change
        self.button = button


class ScaleTareSeen(EventPayload):

    def __init__(self, arrival_time: float):
        super(ScaleTareSeen, self).__init__(arrival_time=arrival_time)
        self._version = "1.0.0"  # Major version incremented on breaking change


class WeightAndFlowUpdate(EventPayload):
    """
    On ScaleProcessor at this time
    """
    # Right now, this doesn't capture any DE1 data, such as state
    # I'm not sure that it needs to with this framework
    def __init__(self, arrival_time: float,
                 scale_time: float,
                 current_weight: float,
                 current_weight_time: float,
                 average_flow: float,
                 average_flow_time: float,
                 median_weight: float,
                 median_weight_time: float,
                 median_flow: float,
                 median_flow_time: float,
                 ):
        super(WeightAndFlowUpdate, self).__init__(arrival_time=arrival_time)
        self._version = "1.0.0"  # Major version incremented on breaking change
        self.scale_time = scale_time
        self.current_weight: float = current_weight
        self.current_weight_time: float = current_weight_time
        self.average_flow: float = average_flow
        self.average_flow_time: float = average_flow_time
        self.median_weight: float = median_weight
        self.median_weight_time: float = median_weight_time
        self.median_flow: float = median_flow
        self.median_flow_time: float = median_flow_time
