"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import json
import logging
import multiprocessing
import os.path
import queue
import threading
import time
from asyncio import Task

from collections import deque
from copy import deepcopy

from typing import Optional, NamedTuple, Dict, Deque

import aiosqlite

from pyDE1.de1.c_api import API_MachineStates
from pyDE1.event_manager.event_manager import EventNotificationAction
from pyDE1.exceptions import DE1TypeError
from pyDE1.signal_handlers import process_shutdown_event
from pyDE1.dispatcher.dispatcher import QUEUE_TOO_DEEP

import pyDE1.database.insert as db_insert

logger = logging.getLogger('DBNotifications')

DB_DIR = '/var/lib/pyDE1'

database_path = os.path.join(DB_DIR, 'pyDE1.sqlite3')

# Don't worry about init for now

def read_queue_to_queue(queue_to_get: multiprocessing.Queue,
                        queue_to_put: asyncio.Queue,
                        loop: asyncio.AbstractEventLoop,
                        shutdown: threading.Event):
    while not shutdown.is_set():
        try:
            data = queue_to_get.get(timeout=1.0)
            # This needs to be started _after_ the loop is running
            # asyncio.get_running_loop().call_soon_threadsafe(
            loop.call_soon_threadsafe(
                queue_to_put.put_nowait, data)
            if (qd := queue_to_put.qsize()) > QUEUE_TOO_DEEP:
                logger.error(
                    "Notification queue exceeded QUEUE_TOO_DEEP, "
                    f"{qd} > {QUEUE_TOO_DEEP}")
        except queue.Empty:
            pass


async def async_queue_get(from_queue: multiprocessing.Queue):
    loop = asyncio.get_running_loop()
    done = False
    data = None  # For exit on shutdown
    while not done and not process_shutdown_event.is_set():
        try:
            # t0 = time.time()
            data = await loop.run_in_executor(
                None,
                from_queue.get, True, 1.0)
                            # blocking, timeout
            # t1 = time.time()
            # logger.info(f"Queue wait time {(t1 - t0)*1000:5.1f} ms")
            done = True
        except queue.Empty:
            pass
    if process_shutdown_event.is_set():
        logger.info("Shut down async_queue_get")
    return data


class RecorderControl (NamedTuple):
    recording: bool
    sequence_id: str


# Target one second of data, or the last-known value
ROLLING_BUFFER_SIZE = {
    'ShotSampleWithVolumesUpdate': 5,   # 4.8 per second on 60 Hz
    'WeightAndFlowUpdate': 10,          # Typically 10 samples per second
    'StateUpdate': 7,                   # Sleep through pour
    'SequencerGateNotification': 16,    # 8 gates to clear and potentially set
    'StopAtNotification': 1,
    'WaterLevelUpdate': 3,              # About 2.5 per second
    'ScaleTareSeen': 3,                 # Limited to 2.5 * period
    'AutoTareNotification': 3,
    'ScaleButtonPress': 3,
    'ConnectivityChange': 8,            # 2 * 4 from disconnected to ready
}
# Total, 59 potential

# If present, only capture (one before and?) all after the sequence begins
ROLLING_BUFFER_TIME_LIMITED = [
    'ShotSampleWithVolumesUpdate',
    'WeightAndFlowUpdate',
    'SequencerGateNotification',
]

# This is probably superfluous, but safer
rolling_buffers_lock = threading.Lock()


# This will likely take a while, run as a task
async def dump_rolling_buffers_to_database(rolling_buffers: Dict[str, Deque],
                                           sequence_id: str,
                                           db: aiosqlite.Connection):

    with rolling_buffers_lock:
        snapshot = deepcopy(rolling_buffers)

    # aiol = logging.getLogger('aiosqlite')
    # old_level = aiol.level
    # aiol.setLevel(logging.DEBUG)
    t0 = time.time()
    count = 0
    async with db.cursor() as cur:
        for rb_class, rb in snapshot.items():
            for notification in rb:
                if rb_class == 'SequencerGateNotification' \
                        and notification['sequence_id'] != sequence_id:
                    pass
                else:
                    await db_insert.dict_notification_cursor_only(
                        notification=notification,
                        sequence_id=sequence_id,
                        cur=cur
                    )
                    count += 1
        await db.commit()
    t1 = time.time()
    logger.info(f"Dump of {count} notifications in {(t1-t0)*1000:.3f} ms")
    # aiol.setLevel(old_level)


async def record_data(incoming: multiprocessing.Queue):

    # Status:
    #   * Before sequence
    #   * In sequence
    #   * Sequence ended

    WAIT_FOR_SEQUENCE_COMPLETE_TIME = 1.0

    consider_sequence_complete = asyncio.Event()

    # Callback on timeout for waiting for sequence complete packet
    def wait_for_recording_stop_callback(task: Task):
        if isinstance(task.exception(), asyncio.CancelledError):
            logger.warning(
                "Timeout waiting for sequence complete to stop recording")
            consider_sequence_complete.set()
            logger.info(
                "Stopping recording with consider_sequence_complete.set()")
        else:
            pass

    rolling_buffers = {}
    for rb_class, rb in ROLLING_BUFFER_SIZE.items():
        rolling_buffers[rb_class] = deque([], rb)

    async with aiosqlite.connect(database_path) as db:
        try:
            recording = False
            sequence_id = 'dummy'
            waiting_for_id = None
            consider_sequence_complete.set()    # Previous sequence is "done"

            while not process_shutdown_event.is_set():
                data = await async_queue_get(incoming)

                if isinstance(data, RecorderControl):
                    recording = data.recording
                    sequence_id = data.sequence_id
                    if recording:   # start
                        waiting_for_id = None
                        consider_sequence_complete.clear()
                        logger.info("Starting recorder")
                        # Kick off "dribble" of back data here
                        # Even at 5 ms per INSERT, could be 100 ms or more
                        asyncio.create_task(
                            dump_rolling_buffers_to_database(
                                rolling_buffers=rolling_buffers,
                                sequence_id=sequence_id,
                                db=db,
                            )
                        )
                    else:   # recording stop
                        waiting_for_id = sequence_id
                        # This is raising asyncio.exceptions.CancelledError
                        t_wait = asyncio.create_task(
                            asyncio.wait_for(
                                consider_sequence_complete.wait(),
                                WAIT_FOR_SEQUENCE_COMPLETE_TIME)
                        )
                        t_wait.add_done_callback(
                            wait_for_recording_stop_callback
                        )
                        logger.info("Waiting for sequence_complete packet")

                elif isinstance(data, str):
                    data_dict = json.loads(data)

                else:
                    raise DE1TypeError(
                        "Unrecognized data type passed for recording:"
                        f"{type(data)}")

                # Always keep the rolling buffers populated
                # this way there is always pre-history available
                # and associated with the sequence_id

                try:
                    with rolling_buffers_lock:
                        rolling_buffers[data_dict['class']].append(data_dict)
                except KeyError:
                    logger.info("No rolling buffer for "
                                f"{data_dict['class']}")
                pass

                if recording or not consider_sequence_complete.is_set():
                    # The history record has already been created
                    # before the RecorderControl message is sent
                    await db_insert.dict_notification(notification=data_dict,
                                                      sequence_id=sequence_id,
                                                      db=db)
                    # Check to see if this is the "matching" sequence complete
                    try:
                        if (not consider_sequence_complete.is_set()
                                and data_dict['class']
                                == 'SequencerGateNotification'
                                and data_dict['name']
                                == SequencerGateName.GATE_SEQUENCE_COMPLETE.value
                                and data_dict['action']
                                == EventNotificationAction.SET.value
                                and data_dict['sequence_id']
                                == waiting_for_id):
                            waiting_for_id = None
                            consider_sequence_complete.set()
                            logger.info("The wait is over")
                    except ValueError:
                        pass

            if process_shutdown_event.is_set():
                logger.info("Shut down record_data() loop")

        except asyncio.CancelledError as e:
            logger.info(e)
            await db.close()
            raise


#
# TODO: Where does this belong?
#

from pyDE1.flow_sequencer import FlowSequencer
from pyDE1.event_manager import SequencerGateNotification, SequencerGateName
from pyDE1.dispatcher.resource import Resource
from pyDE1.dispatcher.implementation import get_resource_to_dict


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


async def create_history_record(flow_sequencer: FlowSequencer):
    """
    The main reason to use aiosqlite here is the ability to detect timeout
    In the case of a timeout, the management of flow should continue
    and the recording of the shot should probably stop, both because
    there is no history record, as well as the likelihood of problems
    with writing to the database.

    TODO: Implement that timeout and logic
    """

    t0 = time.time()

    async with aiosqlite.connect(database_path) as db:

        profile_id = flow_sequencer.de1.latest_profile.id

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
            'active_state': flow_sequencer.active_state.name,
            'start_sequence': flow_sequencer.sequence_start_time,
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
                await resource_to_json(STATE_TO_CONTROL_MAP[
                                     flow_sequencer.active_state]),
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
