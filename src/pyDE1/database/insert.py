"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import json
import time
from typing import Optional

import aiosqlite

import pyDE1
from pyDE1.de1.profile import Profile
from pyDE1.event_manager import SequencerGateName
from pyDE1.event_manager.payloads import EventNotificationAction

logger = pyDE1.getLogger('Database.Insert')


async def profile(profile: Profile, db: aiosqlite.Connection, when: float):
    sql = "SELECT COUNT(*) FROM profile WHERE id == :id"
    cur = await db.execute(sql, {'id': profile.id})
    count = await cur.fetchone()
    if count[0] > 0:
        logger.info(f"Profile {profile.id} already in profile table.")
    else:
        sql = "INSERT INTO profile (id, source, source_format, fingerprint, " \
              "date_added, title, author, notes, beverage_type) " \
              "VALUES (:id, :source, :source_format, :fingerprint, " \
              ":date_added, :title, :author, :notes, :beverage_type)"
        vals = dict()
        for attr in ('id', 'source', 'source_format', 'fingerprint',
                     'title', 'author', 'notes', 'beverage_type'):
            vals[attr] = getattr(profile, attr)
        vals['date_added'] = when
        vals['source_format'] = vals['source_format'].value
        cur: aiosqlite.Cursor = await db.execute(sql, vals)
        await db.commit()
        logger.info(f"Profile {profile.id} added to profile table.")


async def persist_last_profile(profile: Profile, db: aiosqlite.Connection,
                               when: Optional[float] = None):
    if not when:
        when = time.time()
    # Update the last_profile information for persistence
    sql = "UPDATE persist_hkv " \
          "SET value=? " \
          "WHERE header='last_profile' AND key='id'"
    await db.execute(sql, (profile.id,))
    sql = "UPDATE persist_hkv " \
          "SET value=? " \
          "WHERE header='last_profile' AND key='datetime'"
    await db.execute(sql, (when,))
    await db.commit()


async def json_notification(notification: str,
                            sequence_id: str,
                            db: aiosqlite.Connection):
    as_dict = json.loads(notification)
    await  dict_notification(notification=as_dict,
                      sequence_id=sequence_id,
                      db=db)


async def dict_notification(notification: dict,
                            sequence_id: str,
                            db: aiosqlite.Connection):
    class_name = notification['class']
    try:
        method = CLASS_NAME_TO_METHOD[class_name]
        cur: aiosqlite.Cursor = await db.cursor()
        await method(notification=notification,
                     sequence_id=sequence_id,
                     cur=cur)
        await db.commit()
        await cur.close()
    except KeyError:
        logger.debug(f"No {__name__} method for {class_name}")


async def dict_notification_cursor_only(notification: dict,
                                        sequence_id: str,
                                        cur: aiosqlite.Cursor):
    class_name = notification['class']
    try:
        method = CLASS_NAME_TO_METHOD[class_name]
        await method(notification=notification,
                     sequence_id=sequence_id,
                     cur=cur)
    except KeyError:
        logger.debug(f"No {__name__} method for {class_name}")


async def shot_sample_with_volume_update(notification: dict,
                                         sequence_id: str,
                                         cur: aiosqlite.Cursor):
    sql = "INSERT INTO shot_sample_with_volume_update " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, de1_time, sample_time, group_pressure, " \
          "group_flow, mix_temp, head_temp, set_mix_temp, " \
          "set_head_temp, set_group_pressure, set_group_flow, " \
          "frame_number, steam_temp, volume_preinfuse, volume_pour, " \
          "volume_total, volume_by_frames) " \
          "VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :de1_time, :sample_time, :group_pressure, " \
          ":group_flow, :mix_temp, :head_temp, :set_mix_temp, " \
          ":set_head_temp, :set_group_pressure, :set_group_flow, " \
          ":frame_number, :steam_temp, :volume_preinfuse, :volume_pour, " \
          ":volume_total, :volume_by_frames)"
    notification['sequence_id'] = sequence_id
    notification['volume_by_frames'] = str(notification['volume_by_frames'])
    await cur.execute(sql, notification)


async def weight_and_flow_update(notification: dict,
                                 sequence_id: str,
                                 cur: aiosqlite.Cursor):
    sql = "INSERT INTO weight_and_flow_update " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, scale_time, current_weight, current_weight_time," \
          "average_flow, average_flow_time, " \
          "median_weight, median_weight_time, " \
          "median_flow, median_flow_time) " \
          "VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :scale_time, :current_weight, :current_weight_time," \
          ":average_flow, :average_flow_time, " \
          ":median_weight, :median_weight_time, " \
          ":median_flow, :median_flow_time)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def state_update(notification: dict,
                       sequence_id: str,
                       cur: aiosqlite.Cursor):
    sql = "INSERT INTO state_update " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, state, substate, " \
          "previous_state, previous_substate, is_error_state) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :state, :substate, " \
          ":previous_state, :previous_substate, :is_error_state)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def sequencer_gate_notification(notification: dict,
                                      sequence_id: str,
                                      cur: aiosqlite.Cursor):
    sql = "INSERT INTO sequencer_gate_notification " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, name, action, active_state) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :name, :action, :active_state)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)

    # Update the history record, if needed
    action = notification['action']
    name = notification['name']
    if action == EventNotificationAction.SET.value:
        target = None
        if name == SequencerGateName.GATE_FLOW_BEGIN.value:
            target = 'start_flow'
        elif name == SequencerGateName.GATE_FLOW_END.value:
            target = 'end_flow'
        elif name == SequencerGateName.GATE_SEQUENCE_COMPLETE.value:
            target = 'end_sequence'
        if target is not None:
            sql = f"UPDATE sequence SET {target} = ? " \
                  "WHERE sequence.id == ?"
            await cur.execute(sql, (notification['event_time'], sequence_id))


async def stop_at_notification(notification: dict,
                               sequence_id: str,
                               cur: aiosqlite.Cursor):
    sql = "INSERT INTO stop_at_notification " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, stop_at, action, active_state, target_value, " \
          "current_value) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :stop_at, :action, :active_state, :target_value, " \
          ":current_value)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def water_level_update(notification: dict,
                             sequence_id: str,
                             cur: aiosqlite.Cursor):
    sql = "INSERT INTO water_level_update " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, level, start_fill_level) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :level, :start_fill_level)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def scale_tare_seen(notification: dict,
                          sequence_id: str,
                          cur: aiosqlite.Cursor):
    sql = "INSERT INTO scale_tare_seen " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def auto_tare_notification(notification: dict,
                                 sequence_id: str,
                                 cur: aiosqlite.Cursor):
    sql = "INSERT INTO auto_tare_notification " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, action) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :action)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def scale_button_press(notification: dict,
                             sequence_id: str,
                             cur: aiosqlite.Cursor):
    sql = "INSERT INTO scale_button_press " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, button) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :button)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


async def connectivity_change(notification: dict,
                              sequence_id: str,
                              cur: aiosqlite.Cursor):
    sql = "INSERT INTO connectivity_change " \
          "(sequence_id, version, sender, arrival_time, create_time, " \
          "event_time, state, id, name) VALUES " \
          "(:sequence_id, :version, :sender, :arrival_time, :create_time, " \
          ":event_time, :state, :id, :name)"
    notification['sequence_id'] = sequence_id
    await cur.execute(sql, notification)


CLASS_NAME_TO_METHOD = {
    'ShotSampleWithVolumesUpdate': shot_sample_with_volume_update,
    'WeightAndFlowUpdate': weight_and_flow_update,
    'StateUpdate': state_update,
    'SequencerGateNotification': sequencer_gate_notification,
    'StopAtNotification': stop_at_notification,
    'WaterLevelUpdate': water_level_update,
    'ScaleTareSeen': scale_tare_seen,
    'AutoTareNotification': auto_tare_notification,
    'ScaleButtonPress': scale_button_press,
    'ConnectivityChange': connectivity_change,
}