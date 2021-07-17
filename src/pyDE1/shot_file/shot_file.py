"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only


Utilities to be able to write a "shot file" containing the digested data
that describe how the shot progressed
"""
import logging
import time
import warnings

from typing import Optional, Coroutine

from pyDE1.de1.c_api import API_MachineStates
from pyDE1.event_manager import SubscribedEvent
from pyDE1.de1.events import ShotSampleUpdate, ShotSampleWithVolumesUpdate
from pyDE1.scale.events import WeightAndFlowUpdate

# logger = logging.getLogger('ShotFile')

import aiologger
logger = aiologger.Logger.with_default_handlers()


async def basic_shot_sample_logger(ssu: ShotSampleWithVolumesUpdate):
    now = time.time()
    line = "{:5.2f} {:5.2f} {:6.1f} {:2d}     {:5d}  {:0.3f} {:0.3f} ms".format(
        ssu.group_pressure,
        ssu.group_flow,
        ssu.mix_temp,
        ssu.frame_number,
        ssu.sample_time,
        (ssu.create_time - ssu.arrival_time) * 1000,
        (now - ssu.arrival_time) * 1000,
    )
    logger.info(line)


async def gated_basic_shot_sample_logger(sswvu: ShotSampleWithVolumesUpdate):
    warnings.warn(
        "de1._recorder_active will be removed shortly "
        "in favor of database recording in anothe process.")
    now = time.time()
    if sswvu.sender._recorder_active:
        line = "{:5.2f} {:5.2f} {:4.1f} {:2d} {:.1f} {:.1f} {:.1f} {} " \
                "{:5d}  {:0.3f} {:0.3f} ms".format(
            sswvu.group_pressure,
            sswvu.group_flow,
            sswvu.mix_temp,
            sswvu.frame_number,
            sswvu.volume_preinfuse,
            sswvu.volume_pour,
            sswvu.volume_total,
            [round(v,1) for v in sswvu.volume_by_frames],
            sswvu.sample_time,
            (sswvu.create_time - sswvu.arrival_time) * 1000,
            (now - sswvu.arrival_time) * 1000,
        )
        logger.info(line)


class CombinedShotLogger:

    def __init__(self):
        self._last_weight = 0
        self._last_flow = 0

        self._k_ma = 1/10
        self._show_ma_every = 100  # About 5/second

        self._create_ma_sswvu = 1
        self._end_to_end_ma_sswvu = 1
        self._show_ma_count_sswvu = 0

        self._create_ma_wafu = 1
        self._end_to_end_ma_wafu = 1
        self._show_ma_count_wafu = 0


    async def sswvu_subscriber(self, sswvu: ShotSampleWithVolumesUpdate):
        now = time.time()
        self._show_ma_count_sswvu += 1
        t_create = (sswvu.create_time - sswvu.arrival_time) * 1000
        t_end_to_end = (now - sswvu.arrival_time) * 1000
        self._create_ma_sswvu = self._create_ma_sswvu * (1 - self._k_ma) \
                                + t_create * self._k_ma
        self._end_to_end_ma_sswvu = self._end_to_end_ma_sswvu * (1 - self._k_ma) \
                                    + t_end_to_end * self._k_ma
        if self._show_ma_count_sswvu % self._show_ma_every == 0:
            logger.info(
                "SSWVU create, deliver, e2e: "
                "{:.3f}  {:.3f}  {:.3f} ms ".format(
                    self._create_ma_sswvu,
                    self._end_to_end_ma_sswvu - self._create_ma_sswvu,
                    self._end_to_end_ma_sswvu
                )
            )
        if sswvu.sender._recorder_active:
            line = "{:5.2f} b  {:4.2f} mL/s  {:4.2f} g/s  {:5.1f} g  " \
                   "{:4.1f} °C " \
                   "{:2d} {:.1f} {:.1f} {:.1f} {} " \
                   "{:5d}  {:0.3f} {:0.3f} ms".format(
                sswvu.group_pressure,
                sswvu.group_flow,
                self._last_flow,
                self._last_weight,
                sswvu.mix_temp,
                sswvu.frame_number,
                sswvu.volume_preinfuse,
                sswvu.volume_pour,
                sswvu.volume_total,
                [round(v, 1) for v in sswvu.volume_by_frames],
                sswvu.sample_time,
                t_create,
                t_end_to_end,
            )
            logger.info(line)

    async def wafu_subscriber(self, wafu: WeightAndFlowUpdate):
        now = time.time()
        self._show_ma_count_wafu += 1
        t_create = (wafu.create_time - wafu.arrival_time) * 1000
        t_end_to_end = (now - wafu.arrival_time) * 1000
        self._create_ma_wafu = self._create_ma_wafu * (1 - self._k_ma) \
                                + t_create * self._k_ma
        self._end_to_end_ma_wafu = self._end_to_end_ma_wafu * (1 - self._k_ma) \
                                    + t_end_to_end * self._k_ma
        if self._show_ma_count_wafu % self._show_ma_every == 0:
            logger.info(
                "WAFU create, deliver, e2e: "
                "{:.3f}  {:.3f}  {:.3f} ms ".format(
                    self._create_ma_wafu,
                    self._end_to_end_ma_wafu - self._create_ma_wafu,
                    self._end_to_end_ma_wafu
                )
            )
        self._last_flow = wafu.average_flow
        self._last_weight = wafu.current_weight
