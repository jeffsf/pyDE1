"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import functools
import json
import logging
import os
import queue
import threading
import time

from socket import gethostname
from typing import Optional, NamedTuple

import getpass

import aiosqlite
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage, MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from pyDE1.de1.c_api import API_MachineStates, API_Substates
from pyDE1.event_manager import SequencerGateName
from pyDE1.event_manager.event_manager import EventNotificationAction
from pyDE1.exceptions import DE1IncompleteSequenceRecordError
from pyDE1.shot_file.legacy import legacy_shot_file
from pyDE1.database.write_notifications import async_queue_get

format_string = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=logging.DEBUG,
                    format=format_string,
                    )

logger = logging.getLogger('main')
logger_mqtt = logging.getLogger('MQTT')
logger_upload = logging.getLogger('Upload')

MQTT_TOPIC_ROOT = 'pyDE1'

MQTT_CLIENT_ID = f"ui@{gethostname()}[{os.getpid()}]"

MQTT_BROKER_HOSTNAME = '::'
MQTT_BROKER_PORT = 1883

MQTT_TRANSPORT = 'tcp'
MQTT_TLS_CONTEXT = None
MQTT_KEEPALIVE = 60

MQTT_USERNAME = None
MQTT_PASSWORD = None

SERVER_HOST = 'localhost'
SERVER_PORT = 1234
SERVER_ROOT = '/'

DEBUG_MQTT = False


process_shutdown_event = threading.Event()


shot_complete_queue = queue.Queue()


class ShotCompleteItem (NamedTuple):
    sequence_id:    str
    flow_start:     float
    pour_start:     float
    flow_end:       float


def report_upload(sci: ShotCompleteItem,
                  url: Optional[str],
                  success: bool,
                  client: mqtt.Client):

    topic_upload = f"{MQTT_TOPIC_ROOT}/VisualizerUpload"

    payload = sci._asdict()
    payload['url'] = url
    payload['success'] = success

    client.publish(
        topic=topic_upload,
        payload=json.dumps(payload),
        retain=True
    )


async def run_mqtt() -> mqtt.Client:
    """
    Configure the MQTT client, start it, and return it
    so that it can be used to publish on upload result
    (returns with MQTT client loop running in executor)
    """

    userdata_dict = {
        "sequence_id": None,
        "in_sequence": False,
        "flow_start": 0,
        "pour_start": 0,
        "flow_end": 0,
    }

    # Set up the MQTT client

    topic_states = f"{MQTT_TOPIC_ROOT}/StateUpdate"
    topic_gates = f"{MQTT_TOPIC_ROOT}/SequencerGateNotification"

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        logger.debug(f"MQTT Connect: flags: {flags}, reasonCode: {reasonCode}, "
              f"properties {properties}")
        client.subscribe(topic_states)
        client.subscribe(topic_gates)

    def on_message_callback(client: mqtt.Client, userdata,
                            message: MQTTMessage):

        payload_dict = json.loads(message.payload)

        logger_mqtt.debug(f"Received: {message.topic} {message.payload}")

        if message.topic == topic_gates:
            sequence_id = payload_dict['sequence_id']
            name = payload_dict['name']
            action = payload_dict['action']
            active_state = payload_dict['active_state']
            event_time = payload_dict['event_time']

            if action == EventNotificationAction.CLEAR.value:
                pass

            # TODO: Confirm or make gate notifications track state-change times

            elif not userdata['in_sequence']:
                if name == SequencerGateName.GATE_SEQUENCE_START.value \
                        and active_state == API_MachineStates.Espresso.name:
                    userdata['in_sequence'] = True
                    userdata['sequence_id'] = sequence_id
                    userdata['flow_start'] = 0
                    userdata['pour_start'] = 0
                    userdata['flow_end'] = 0
                    logger_mqtt.info(f"Sequence started {sequence_id}")
                else:
                    pass    # Assumes gates arrive in order

            else:   # in a sequence

                if sequence_id != userdata['sequence_id']:
                    logger_mqtt.error("Unexpected sequence id: "
                              f"got {id}, aborting sequence")
                    userdata['in_sequence'] = False

                if name == SequencerGateName.GATE_FLOW_BEGIN.value:
                    userdata['flow_start'] = event_time
                    logger_mqtt.info('Flow started')

                elif name == SequencerGateName.GATE_FLOW_END.value:
                    userdata['flow_end'] = event_time
                    logger_mqtt.info('Flow ended')

                elif name == SequencerGateName.GATE_SEQUENCE_COMPLETE.value:
                    userdata['in_sequence'] = False
                    logger_mqtt.info('Upload triggered')
                    shot_complete_queue.put_nowait(
                        ShotCompleteItem(
                            sequence_id=userdata['sequence_id'],
                            flow_start=userdata['flow_start'],
                            pour_start=userdata['pour_start'],
                            flow_end=userdata['flow_end'],
                        )
                    )
                    t_pi = userdata['pour_start'] - userdata['flow_start']
                    t_pour = userdata['flow_end'] - userdata['pour_start']
                    t_total = userdata['flow_end'] - userdata['flow_start']
                    logger_mqtt.info(
                        f"Timing: {t_pi:.0f} + {t_pour:.0f} for "
                        f"{t_total:.0f} seconds"
                    )

                else:
                    pass

        elif message.topic == topic_states:

            # Don't really need this, but will for GUI to split
            # preinfuse and flow time for display

            if (userdata['in_sequence']
                    and payload_dict['previous_substate']
                        != API_Substates.Pour.name
                    and payload_dict['substate']
                        == API_Substates.Pour.name):
                userdata['pour_start'] = payload_dict['event_time']
                logger_mqtt.info('Pour start')

        else:
            pass

    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        clean_session=None,  # Required for MQTT5
        userdata=userdata_dict,
        protocol=MQTTv5,
        transport=MQTT_TRANSPORT,
    )

    if DEBUG_MQTT:
        mqtt_logger = logging.getLogger('Paho')
        mqtt_logger.setLevel(logging.DEBUG)
        mqtt_client.enable_logger(mqtt_logger)

    mqtt_client.on_connect = on_connect_callback
    mqtt_client.on_message = on_message_callback

    mqtt_client.connect(host=MQTT_BROKER_HOSTNAME,
                   port=MQTT_BROKER_PORT,
                   keepalive=MQTT_KEEPALIVE,
                   bind_address="",
                   bind_port=0,
                   clean_start=MQTT_CLEAN_START_FIRST_ONLY,
                   properties=None)

    loop.run_in_executor(None, mqtt_client.loop_forever)

    return mqtt_client


async def loop_on_queue(username: str, password: str,
                        client: mqtt.Client):

    async with aiosqlite.connect('/var/lib/pyDE1/pyDE1.sqlite3') as db:
        while not process_shutdown_event.is_set():
            got: ShotCompleteItem = await async_queue_get(
                from_queue=shot_complete_queue)

            sid = got.sequence_id

            # As the database is processing these packets real-time as well
            # it is possible that the sequence row hasn't been updated yet
            # This will result in DE1DBIncompleteSequenceRecord being raised

            contents = None
            for cnt in range(0,10):
                try:
                    await asyncio.sleep(0.100)  # 100 ms
                    contents = await legacy_shot_file(sequence_id=sid, db=db)
                    break
                except DE1IncompleteSequenceRecordError as e:
                    logger.debug(e)
            if contents is None:
                logger.error("Did not recover, aborting upload: {e}")
                report_upload(sci=got, url=None, success=False,
                              client=client)
                continue

            fd = {
                'file': contents,
                'filename': f"{sid}.shot"
            }

            r = await asyncio.get_running_loop().run_in_executor(
                None,
                functools.partial(
                    requests.post,
                    url='https://visualizer.coffee/api/shots/upload',
                    files=fd,
                    auth=HTTPBasicAuth(username=username,
                                       password=password)
                ))
            f"Upload returned: {r.status_code} {r.reason} {r.text}"
            r: requests.Response
            if r.ok:
                d = json.loads(r.text)
                url = f"https:///visualizer.coffee/shots/{d['id']}"
                logger.info(url)
                report_upload(sci=got, url=url, success=True,
                              client=client)
            else:
                report_upload(sci=got, url=None, success=False,
                              client=client)


async def setup_and_run(username: str,
                        password: str):

    client = await run_mqtt()
    logger.info(client)
    await loop_on_queue(username=username,
                        password=password,
                        client=client)


if __name__ == '__main__':

    username = 'you@example.com'
    password = getpass.getpass()

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    loop.create_task(setup_and_run(username=username,
                                   password=password))

    loop.run_forever()


