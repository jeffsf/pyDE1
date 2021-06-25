"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only


Estimators to use with ScaleProcessor
"""

import logging

# from statistics import mean
from statistics import median
from typing import Tuple, List

from pyDE1.scale.processor import ScaleProcessor, ScaleProcessorError

logger = logging.getLogger('Estimator')

# Test to see how much of the ~4.5 ms delay is coming from calling mean()
# Quick check shows delay dropped to ~2.5 ms, so leaving False for now
# Resulting std. dev. is probably around 100 ms / sqrt(2)\

# TODO: Come back and revisit this decision
_USE_MEAN_FOR_TIME = True

# This drops the delay to ~2.5 ms as well
def mean(data: List[float]):
    return sum(data)/len(data)

# A perhaps good-enough median estimator (lower of even-length list)
# Still around 2.4 ms, so not really a significant gain -- use statistics.median
# def median(data: List[float]):
#     # .sort() is in-place
#     dcopy = data.copy()
#     dcopy.sort()
#     return dcopy[int(len(data)/2)]


class Estimator:
    """
    Generic estimator

    Writes the value into scale_processor.target_attr
    Writes the time into scale_processor.target_attr_time
    Assumes that scale_processor._history is a list

    In contrast to other implementations, the time estimates
    include scale_delay and estimated_period/2
    """

    def __init__(self, scale_processor: ScaleProcessor,
                 target_attr: str):
        self._scale_processor = scale_processor
        self._target_attr = target_attr
        # sanity check, don't be writing non-existent attributes
        # hasattr() "is implemented by calling getattr(object, name)"
        try:
            getattr(self._scale_processor, self._target_attr)
            getattr(self._scale_processor, self._target_attr + "_time")
        except AttributeError as e:
            raise e  # in case one day I get fancier, dev-only likely

        # Number of samples needed to estimate, set from subclass
        self._needed_internal: int = 1

    def estimate(self):
        if self._scale_processor._history_available >= self._needed:
            (val, tval) = self._estimate_inner()
            tval -= (self._scale_processor.scale.sensor_lag
                     + self._scale_processor.scale.nominal_period / 2)
        else:
            val = 0
            tval = 0
        setattr(self._scale_processor, self._target_attr, val)
        setattr(self._scale_processor, self._target_attr + "_time", tval)

    def _estimate_inner(self) -> Tuple[float, float]:
        raise NotImplementedError

    @property
    def _needed(self):
        return self._needed_internal

    @_needed.setter
    def _needed(self, needed: int):
        # Arguably this should grab _history_lock, but increases here
        # should be "safe" and recoverable. Keep as non-async
        self._needed_internal = needed
        sp = self._scale_processor
        sp._history_max = max(needed, sp._history_max)


class CurrentWeight (Estimator):

    def __init__(self, scale_processor: ScaleProcessor,
                 target_attr: str):
        super(CurrentWeight, self).__init__(scale_processor=scale_processor,
                                            target_attr=target_attr)
        self._needed = 1

    def _estimate_inner(self):
        val = self._scale_processor._history_weight[-1]
        tval = self._scale_processor._history_time[-1]
        return val, tval


class AverageFlow (Estimator):

    def __init__(self, scale_processor: ScaleProcessor,
                 target_attr: str,
                 samples: int):
        super(AverageFlow, self).__init__(scale_processor=scale_processor,
                                          target_attr=target_attr)
        self.samples = samples

    def _estimate_inner(self):
        # time data is jittery, use the best estimate
        dt = self.samples * self._scale_processor.scale.estimated_period
        val = ((self._scale_processor._history_weight[-1]
                - self._scale_processor._history_weight[-self.samples]) / dt)
        # (latest - dt/2) has a deviation of sigma + that of dt (small)
        # (latest + oldest)/2 has a deviation of sigma/sqrt(2) if independent
        # Following this, the average over the window should be even better
        if _USE_MEAN_FOR_TIME:
            tval = mean(self._scale_processor._history_time[-self.samples:])
        else:
            tval = (self._scale_processor._history_time[-self.samples]
                    + self._scale_processor._history_time[-1]) / 2
        return val, tval

    @property
    def samples(self):
        return self._samples

    @samples.setter
    def samples(self, value):
        self._samples = value
        self._needed = value


class MedianWeight (Estimator):

    def __init__(self, scale_processor: ScaleProcessor, target_attr: str,
                 samples: int):
        super(MedianWeight, self).__init__(scale_processor=scale_processor,
                                           target_attr=target_attr)
        self.samples = samples

    def _estimate_inner(self):
        val = median(self._scale_processor._history_weight[-self.samples:])
        if _USE_MEAN_FOR_TIME:
            tval = mean(self._scale_processor._history_time[-self.samples:])
        else:
            tval = (self._scale_processor._history_time[-self.samples]
                    + self._scale_processor._history_time[-1]) / 2
        return val, tval

    @property
    def samples(self):
        return self._samples

    @samples.setter
    def samples(self, value):
        self._samples = value
        self._needed = value


class MedianFlow (Estimator):
    """
    Estimate as finite difference between two medians

     samples_for_median                      samples_for_median
    -15 -14 -13 -12 -11 -10  -9  -8  -7  -6  -5  -4  -3  -2  -1
      |...............|                       |...............|
              |_______________________________________|
                               samples

    Similar to previous, deviation for average of the four points
    is better than that of one point offset by n * dt
    """

    def __init__(self, scale_processor: ScaleProcessor, target_attr: str,
                 samples: int, samples_for_medians: int):
        super(MedianFlow, self).__init__(scale_processor=scale_processor,
                                           target_attr=target_attr)
        self._samples = samples
        self._samples_for_medians = samples_for_medians
        # For side effects
        self.samples = samples
        self.samples_for_medians = samples_for_medians

    def _estimate_inner(self):
        p0 = -1
        p1 = -self.samples_for_medians
        p2 = -(1 + self.samples)
        p3 = -(self.samples + self.samples_for_medians)
        m0 = median(self._scale_processor._history_weight[p1:p0])
        m1 = median(self._scale_processor._history_weight[p3:p2])
        dt = self.samples * self._scale_processor.scale.estimated_period
        val = (m0 - m1)/dt
        if _USE_MEAN_FOR_TIME:
            tval = mean(self._scale_processor._history_time[p3:p0])
        else:
            tval = (self._scale_processor._history_time[p3]
                    + self._scale_processor._history_time[p0]) / 2
        return val, tval

    @property
    def samples(self):
        return self._samples

    @samples.setter
    def samples(self, value):
        self._samples = value
        self._needed = self.samples + self.samples_for_medians

    @property
    def samples_for_medians(self):
        return self._samples_for_medians

    @samples_for_medians.setter
    def samples_for_medians(self, value):
        self._samples_for_medians = value
        self._needed = self.samples + self.samples_for_medians