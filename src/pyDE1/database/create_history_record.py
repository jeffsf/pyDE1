"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Executes in FlowSequencer context, kept in database directory
"""
import json
import time
from typing import Optional

import aiosqlite

from pyDE1.config import config
from pyDE1.de1.c_api import API_MachineStates
from pyDE1.dispatcher.implementation import get_resource_to_dict
from pyDE1.dispatcher.resource import Resource
from pyDE1.event_manager import SequencerGateNotification


async def resource_to_json(resource: Resource):

    resource_dict = await get_resource_to_dict(resource)

    # In HTTP API this gets pretty printed
    # content = json.dumps(content,
    #                      sort_keys=True, indent=4) + "\n"
    # Here we're even farther removed from human eyes
    # and under time pressure

    return json.dumps(resource_dict)


STATE_TO_CONTROL_MAP = {
    API_MachineStates.Espresso: Resource.DE1_CONTROL_ESPRESSO,
    API_MachineStates.Steam: Resource.DE1_CONTROL_STEAM,
    API_MachineStates.HotWater: Resource.DE1_CONTROL_HOT_WATER,
    API_MachineStates.HotWaterRinse: Resource.DE1_CONTROL_HOT_WATER_RINSE
}


async def create_history_record(active_state: API_MachineStates,
                                sequence_start_time: float,
                                profile_id: Optional[str]):
    """
    The main reason to use aiosqlite here is the ability to detect timeout
    In the case of a timeout, the management of flow should continue
    and the recording of the shot should probably stop, both because
    there is no history record, as well as the likelihood of problems
    with writing to the database.

    TODO: Implement that timeout and logic
    """

    t0 = time.time()

    async with aiosqlite.connect(config.database.FILENAME) as db:

        # The database keeps track of the most-recently uploaded profile
        # if there isn't one known by the DE1
        # Happy path: de1 profile id present
        #   Use it
        # Unhappy path: de1 profile null
        #   Option 1 - Query first, include in single commit
        #   Option 2 - INSERT then UPDATE with SELECT and commit

        # https://www.sqlite.org/quirks.html#no_separate_boolean_datatype
        if profile_id is not None:
            profile_assumed = False     # Should match SQLite3 FALSE token
        else:
            profile_assumed = True      # Should match SQLite3 TRUE token
            cur = await db.execute("SELECT value FROM persist_hkv "
                                   "WHERE header == 'last_profile' "
                                   "AND key == 'id'")
            (profile_id,) = await cur.fetchone()

        # Only include fields that have known data

        vals = {
            'id': SequencerGateNotification.sequence_id,
            'active_state': active_state.name,
            'start_sequence': sequence_start_time,
            'profile_id': profile_id,
            'profile_assumed': profile_assumed,
            'resource_version':
                await resource_to_json(Resource.VERSION),
            'resource_de1_id':
                await resource_to_json(Resource.DE1_ID),
            'resource_de1_read_once':
                await resource_to_json(Resource.DE1_READ_ONCE),
            'resource_de1_calibration_flow_multiplier':
                await resource_to_json(
                    Resource.DE1_CALIBRATION_FLOW_MULTIPLIER),
            'resource_de1_control_mode':
                await resource_to_json(STATE_TO_CONTROL_MAP[active_state]),
            'resource_de1_control_tank_water_threshold':
                await resource_to_json(
                    Resource.DE1_CONTROL_TANK_WATER_THRESHOLD),
            'resource_de1_setting_before_flow':
                await resource_to_json(Resource.DE1_SETTING_BEFORE_FLOW),
            'resource_de1_setting_steam':
                await resource_to_json(Resource.DE1_SETTING_STEAM),
            'resource_de1_setting_target_group_temp':
                await resource_to_json(Resource.DE1_SETTING_TARGET_GROUP_TEMP),
            # Confirm that this returns something with no scale
            'resource_scale_id':
                await resource_to_json(Resource.SCALE_ID)
        }

        sql = "INSERT INTO sequence" \
              "(id, active_state, start_sequence, " \
              "profile_id, profile_assumed, " \
              "resource_version, resource_de1_id, resource_de1_read_once, " \
              "resource_de1_calibration_flow_multiplier, " \
              "resource_de1_control_mode, " \
              "resource_de1_control_tank_water_threshold, " \
              "resource_de1_setting_before_flow, " \
              "resource_de1_setting_steam, " \
              "resource_de1_setting_target_group_temp, " \
              "resource_scale_id) " \
              "VALUES " \
              "(:id, :active_state, :start_sequence, " \
              ":profile_id, :profile_assumed, " \
              ":resource_version, :resource_de1_id, " \
              ":resource_de1_read_once, " \
              ":resource_de1_calibration_flow_multiplier, " \
              ":resource_de1_control_mode, " \
              ":resource_de1_control_tank_water_threshold, " \
              ":resource_de1_setting_before_flow, " \
              ":resource_de1_setting_steam, " \
              ":resource_de1_setting_target_group_temp, " \
              ":resource_scale_id)"
        cur = await db.execute(sql, vals)
        await db.commit()