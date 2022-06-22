"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import email.utils
import json
import sqlite3
import time
# For the output of local_time
from datetime import datetime
from typing import NamedTuple, List, Union, Tuple

import aiosqlite

import pyDE1
import pyDE1.pyde1_logging as pyde1_logging
from pyDE1.exceptions import DE1IncompleteSequenceRecordError

logger = pyDE1.getLogger('LegacyShotFile')


class ShotRow (NamedTuple):
   de1_time:            float
   sample_time:         int
   group_pressure:      float
   group_flow:          float
   mix_temp:            float
   head_temp:           float
   set_mix_temp:        float
   set_head_temp:       float
   set_group_pressure:  float
   set_group_flow:      float
   frame_number:        int
   steam_temp:          float
   volume_preinfuse:    float
   volume_pour:         float
   volume_total:        float
   volume_by_frames:    str     # representation of list


def shot_row_factory(cur: sqlite3.Cursor, row: sqlite3.Row):
    return ShotRow(*row)


class SequenceRow (NamedTuple):
    id: str
    active_state:   str
    start_sequence: float
    start_flow:     float
    end_flow:       float
    end_sequence:   float
    profile_id:     str
    # https://www.sqlite.org/quirks.html#no_separate_boolean_datatype
    profile_assumed:    int     # 0: False, 1: True
    resource_version:                           str
    resource_de1_id:                            str
    resource_de1_read_once:                     str
    resource_de1_calibration_flow_multiplier:   str
    resource_de1_control_mode:                  str
    resource_de1_control_tank_water_threshold:  str
    resource_de1_setting_before_flow:           str
    resource_de1_setting_steam:                 str
    resource_de1_setting_target_group_temp:     str
    resource_scale_id:                          str


def sequence_row_factory(cur: sqlite3.Cursor, row: sqlite3.Row):
    return SequenceRow(*row)


class WeightRow (NamedTuple):
     current_weight:        float
     current_weight_time:   float


def weight_row_factory(cur: sqlite3.Cursor, row: sqlite3.Row):
    return WeightRow(*row)


class FlowRow(NamedTuple):
    average_flow:       float
    average_flow_time:  float


def flow_row_factory(cur: sqlite3.Cursor, row: sqlite3.Row):
    return FlowRow(*row)


class ProfileRow (NamedTuple):
    id:             str
    # source          bytes,
    source_format:  str
    fingerprint:    str
    date_added:     float
    title:          str
    author:         str
    notes:          str
    beverage_type:  str


def profile_row_factory(cur: sqlite3.Cursor, row: sqlite3.Row):
    return ProfileRow(*row)


def braced_list(list_of_items: Union[List, Tuple]):
    return '{' + ' '.join(list_of_items) + '}'


async def legacy_shot_file(sequence_id: str,
                           db: aiosqlite.Connection):

    # contents will be joined with newlines prior to return
    contents = []
    # sequence_id is, or had better be, only hex digits with no spaces
    contents.append(f"sequence_id {sequence_id}")

    db.row_factory = sequence_row_factory
    cur = await db.execute(f"SELECT {' ,'.join(SequenceRow._fields)} "
                           f"FROM sequence WHERE id = ?", (sequence_id,))
    cur: aiosqlite.Cursor
    sequence_row: SequenceRow = await cur.fetchone()
    logger.debug(sequence_row)

    if sequence_row is None or None in (sequence_row.start_sequence,
                sequence_row.start_flow,
                sequence_row.end_flow,
                sequence_row.end_sequence):
        raise DE1IncompleteSequenceRecordError(
            f"Whoa there, not ready? {sequence_row})")

    contents.append(f"clock {round(sequence_row.start_flow)}")
    formatted_start_time = email.utils.format_datetime(
        datetime.fromtimestamp(sequence_row.start_flow).astimezone())
    contents.append(
        f"local_time {braced_list((formatted_start_time,))}")

    # Collect ShotSample data

    db.row_factory = shot_row_factory
    cur = await db.execute(
        f"SELECT {', '.join(ShotRow._fields)} "
        "FROM shot_sample_with_volume_update "
        "WHERE sequence_id = :sequence_id "
        "AND de1_time BETWEEN :start_flow AND :end_flow "
        "ORDER BY de1_time",
        (sequence_id, sequence_row.start_flow, sequence_row.end_flow))

    shot_rows: List[ShotRow] = await cur.fetchall()

    espresso_elapsed = [
        '{:.3f}'.format(r.de1_time - sequence_row.start_flow)
        for r in shot_rows
    ]
    contents.append(f"espresso_elapsed {braced_list(espresso_elapsed)}")

    espresso_pressure = [
        '{:.2f}'.format(r.group_pressure) for r in shot_rows
    ]
    contents.append(f"espresso_pressure {braced_list(espresso_pressure)}")

    espresso_flow = [
        '{:.2f}'.format(r.group_flow) for r in shot_rows
    ]
    contents.append(f"espresso_flow {braced_list(espresso_flow)}")

    espresso_temperature_basket = [
        '{:.2f}'.format(r.head_temp) for r in shot_rows
    ]
    contents.append("espresso_temperature_basket "
                    f"{braced_list(espresso_temperature_basket)}")

    espresso_temperature_mix = [
        '{:.2f}'.format(r.mix_temp) for r in shot_rows
    ]
    contents.append("espresso_temperature_mix "
                    f"{braced_list(espresso_temperature_mix)}")

    # This is scaled down by 10x in the legacy format
    espresso_water_dispensed = [
        '{:.2f}'.format(r.volume_total/10) for r in shot_rows
    ]
    contents.append(
        "WARNING {espresso_water_dispensed scaled by 10 "
        "for legacy compatibility}")
    contents.append("espresso_water_dispensed "
                    f"{braced_list(espresso_water_dispensed)}")

    espresso_temperature_goal = [
        '{:.2f}'.format(r.set_mix_temp) for r in shot_rows
    ]
    contents.append("espresso_temperature_goal "
                    f"{braced_list(espresso_temperature_goal)}")

    espresso_pressure_goal = [
        '{:.2f}'.format(r.set_group_pressure) for r in shot_rows
    ]
    contents.append("espresso_pressure_goal "
                    f"{braced_list(espresso_pressure_goal)}")

    espresso_flow_goal = [
        '{:.2f}'.format(r.set_group_flow) for r in shot_rows
    ]
    contents.append("espresso_flow_goal "
                    f"{braced_list(espresso_flow_goal)}")

    espresso_frame_number = [
        '{:d}'.format(r.frame_number) for r in shot_rows
    ]
    contents.append("espresso_frame_number "
                    f"{braced_list(espresso_frame_number)}")

    def bogus(frame_number: int):
        if frame_number % 2:
            return "10000000"
        else:
            return "-10000000"

    espresso_state_change = [
        bogus(r.frame_number) for r in shot_rows
    ]
    contents.append("espresso_state_change "
                    f"{braced_list(espresso_state_change)}")

    # About 2^-13 for a U16P12 value
    MIN_FLOW_FOR_CALC = 0.0001

    espresso_resistance = [
        '{:.2f}'.format(r.group_pressure /
                         max(r.group_flow, MIN_FLOW_FOR_CALC)**2)
        for r in shot_rows
    ]
    contents.append("espresso_resistance "
                    f"{braced_list(espresso_resistance)}")

    #
    # On to the scale
    #

    db.row_factory = weight_row_factory
    cur = await db.execute(
        f"SELECT {', '.join(WeightRow._fields)} "
        "FROM weight_and_flow_update "
        "WHERE sequence_id = :sequence_id "
        "AND current_weight_time BETWEEN :start_time AND :end_time "
        "ORDER BY current_weight_time",
        (sequence_id, sequence_row.start_flow, sequence_row.end_sequence))

    weight_rows: List[WeightRow] = await cur.fetchall()

    db.row_factory = flow_row_factory
    cur = await db.execute(
        f"SELECT {', '.join(FlowRow._fields)} "
        "FROM weight_and_flow_update "
        "WHERE sequence_id = :sequence_id "
        "AND average_flow_time BETWEEN :start_time AND :end_time "
        "ORDER BY average_flow_time",
        (sequence_id, sequence_row.start_flow, sequence_row.end_sequence))

    flow_rows: List[FlowRow] = await cur.fetchall()

    #
    # Legacy de1app behavior is to take the value just before the DE1 sample
    #

    # timeit on some variants here

    # O(n2) methods end up around 70 ms per series
    # list(filter(lambda r: r.current_weight_time < some_time, weight_rows)[-1]
    #   the last one is the "right" one, need to iterate all
    # next(filter(lambda r: r.current_weight_time >= some_time, weight_rows)
    #   the first one is the one just after, not before the time
    # O(n) method around 0.8 ms per series per execution (without formatting)
    # import timeit
    # n = 100
    # test_result = timeit.timeit(
    #     'emulate_ds(shot_rows, weight_rows, flow_rows)',
    #     globals=locals(),
    #     number=n)
    # print(f"{1000 * test_result / n:0.3f} ms per execution -- emulate_ds")

    def emulate_ds(shot: List[ShotRow],
                   weight: List[WeightRow],
                   flow: List[FlowRow]):
        idx_weight = 1
        idx_flow = 1
        last_w = len(weight) - 1
        last_f = len(flow) - 1
        retval_weight = []
        retval_flow = []

        for sr in shot:

            if last_w >= 1:
                while weight[idx_weight].current_weight_time < sr.de1_time \
                        and idx_weight < last_w:
                    idx_weight += 1
                retval_weight.append(
                    '{:.2f}'.format(weight[idx_weight-1].current_weight))

            if last_f >= 1:
                while flow[idx_flow].average_flow_time < sr.de1_time \
                        and idx_flow < last_f:
                    idx_flow += 1
                retval_flow.append(
                    '{:.2f}'.format(flow[idx_flow-1].average_flow))

        return retval_weight, retval_flow

    (espresso_weight, espresso_flow_weight) = emulate_ds(
        shot=shot_rows, weight=weight_rows, flow=flow_rows)


    contents.append("espresso_weight "
                    f"{braced_list(espresso_weight)}")

    contents.append("espresso_flow_weight "
                    f"{braced_list(espresso_flow_weight)}")

    # settings {
    #   drink_weight 12.3
    #   beverage_type
    # }
    # max of median flow after flow end, before end of sequence

    db.row_factory = None
    cur = await db.execute(
        f"SELECT max(median_weight) "
        "FROM weight_and_flow_update "
        "WHERE sequence_id = :sequence_id "
        "AND median_weight_time BETWEEN :start_time AND :end_time "
        "ORDER BY average_flow_time",
        (sequence_id, sequence_row.end_flow, sequence_row.end_sequence))

    (drink_weight,) = await cur.fetchone()

    db.row_factory = profile_row_factory
    cur = await db.execute(
        f"SELECT {', '.join(ProfileRow._fields)} "
        "FROM profile "
        "WHERE id = :id ",
        (sequence_row.profile_id,))

    profile_row: ProfileRow = await cur.fetchone()

    braced_name = braced_list((profile_row.title,))
    braced_bev_type = braced_list((profile_row.beverage_type,))

    contents.append("settings {")
    contents.append(f"\tprofile_title {braced_name}")
    contents.append(f"\tdrink_weight {drink_weight:0.1f}")
    contents.append(f"\tbeverage_type {braced_bev_type}")
    contents.append("}")

    # profile {
    #   (json)
    # }
    # Not used by Visualizer
    contents.append(f"profile {json.dumps(profile_row._asdict(), indent=2)}")

    return '\n'.join(contents) + "\n"


async def get_latest_espresso_id(db: aiosqlite.Connection) -> SequenceRow:

    db.row_factory = sequence_row_factory
    cur = await db.execute(f"SELECT {', '.join(SequenceRow._fields)} "
                           "FROM sequence "
                           "WHERE active_state == 'Espresso'"
                           "ORDER BY start_sequence DESC "
                           "LIMIT 1")
    return await cur.fetchone()


if __name__ == '__main__':

    import argparse

    from pyDE1.config import config

    ap = argparse.ArgumentParser(
        description="""Main executable to start the pyDE1 core.

        """
        f"Default configuration file is at {config.DEFAULT_CONFIG_FILE}"
    )
    ap.add_argument('-c', type=str, help='Use as alternate config file')

    args = ap.parse_args()

    pyde1_logging.setup_initial_logger()

    config.load_from_yaml(args.c)

    pyde1_logging.setup_direct_logging(config.logging)
    pyde1_logging.config_logger_levels(config.logging)

    async def run():
        async with aiosqlite.connect(config.database.FILENAME) as db:
            t0 = time.time()
            sr: SequenceRow = await get_latest_espresso_id(db)
            lsf = await legacy_shot_file(sr.id, db)
            t1 = time.time()
            print("-----")
            print(lsf, end='')
            print("-----")
            with open('test.shot', 'w') as fh:
                print(lsf, file=fh)
            print("Elapsed to retrieve and format: "
                  f"{(t1 - t0)*1000:0.1f} ms")

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    loop.run_until_complete(run())