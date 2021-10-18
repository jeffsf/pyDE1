"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import json
import multiprocessing
import queue
import threading
import time
from asyncio import Task
from collections import deque
from copy import deepcopy
from typing import Dict, Deque

import aiosqlite

import pyDE1
import pyDE1.database.insert as db_insert
import pyDE1.shutdown_manager as sm
from pyDE1.config import config
from pyDE1.database.recorder_control import RecorderControl

# from pyDE1.dispatcher.dispatcher import QUEUE_TOO_DEEP
QUEUE_TOO_DEEP = 1

from pyDE1.event_manager import SequencerGateName
from pyDE1.event_manager.payloads import EventNotificationAction
from pyDE1.exceptions import DE1TypeError



logger = pyDE1.getLogger('Database.Notifications')


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
    while not done and not sm.shutdown_underway.is_set():
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
    if sm.shutdown_underway.is_set():
        logger.info("Shut down async_queue_get")
    return data


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

    async with aiosqlite.connect(config.database.FILENAME) as db:
        try:
            recording = False
            sequence_id = 'dummy'
            waiting_for_id = None
            consider_sequence_complete.set()    # Previous sequence is "done"

            while not sm.shutdown_underway.is_set():
                data = await async_queue_get(incoming)

                if isinstance(data, str):
                    data_dict = json.loads(data)
                    # Always keep the rolling buffers populated
                    # this way there is always pre-history available
                    # and associated with the sequence_id

                    try:
                        with rolling_buffers_lock:
                            rolling_buffers[data_dict['class']].append(
                                data_dict)
                    except KeyError:
                        logger.info("No rolling buffer for "
                                    f"{data_dict['class']}")
                    pass

                    if recording or not consider_sequence_complete.is_set():
                        # The history record has already been created
                        # before the RecorderControl message is sent
                        await db_insert.dict_notification(
                            notification=data_dict,
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

                elif isinstance(data, RecorderControl):
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

                else:
                    if not sm.shutdown_underway.is_set():
                        raise DE1TypeError(
                            "Unrecognized data type passed for recording:"
                            f"{type(data)}")
                    else:
                        continue

            if sm.shutdown_underway.is_set():
                logger.info("Shut down record_data() loop")

        except asyncio.CancelledError as e:
            logger.info(e)
            await db.close()
            raise


