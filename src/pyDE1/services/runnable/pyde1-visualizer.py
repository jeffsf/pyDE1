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
import logging.handlers
import os
import os.path
import queue

from pprint import pformat
from socket import gethostname
from typing import Optional, NamedTuple, Callable

import aiosqlite
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage, MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from pyDE1.config_load import ConfigYAML, ConfigLoadable

import pyDE1.shutdown_manager as sm
from pyDE1.de1.c_api import API_MachineStates, API_Substates
from pyDE1.event_manager import SequencerGateName
from pyDE1.event_manager.payloads import EventNotificationAction
from pyDE1.exceptions import DE1IncompleteSequenceRecordError
from pyDE1.shot_file.legacy import legacy_shot_file
# from pyDE1.database.write_notifications import async_queue_get

# The default config file can be missing without error
# If specified on the command line and missing is fatal

import pyDE1
import pyDE1.pyde1_logging as pyde1_logging
from pyDE1.pyde1_logging import ConfigLogging


class Config (ConfigYAML):

    DEFAULT_CONFIG_FILE = '/usr/local/etc/pyde1/pyde1-visualizer.conf'

    def __init__(self):
        super(Config, self).__init__()
        self.database = _Database()
        self.logging = _Logging()
        self.mqtt = _MQTT()
        self.visualizer = _Visualizer()


    # This craziness is so pyCharm autocompletes
    # Otherwise typing.SimpleNamespace() would be sufficient

class _MQTT (ConfigLoadable):
    def __init__(self):
        self.TOPIC_ROOT = 'pyDE1'
        self.CLIENT_ID_PREFIX = 'pyde1-visualizer'
        self.BROKER_HOSTNAME = '::1'
        self.BROKER_PORT = 1883
        self.TRANSPORT = 'tcp'
        self.KEEPALIVE = 60
        self.USERNAME = None
        self.PASSWORD = None
        self.DEBUG = False
        self.TLS = False    # Set True, or rest of TLS is ignored
        # See paho Client.tls_set() for details
        self.TLS_CA_CERTS = None
        self.TLS_CERTFILE = None
        self.TLS_KEYFILE = None
        self.TLS_CERT_REQS = None
        self.TLS_VERSION = None
        self.TLS_CIPHERS = None


class _Visualizer (ConfigLoadable):
    def __init__(self):
        self.USERNAME = 'you@example.com'
        self.PASSWORD = 'your password or upload token here'
        self.MIN_FLOW_TIME = 10  # seconds, or not uploaded


class _Logging (ConfigLogging):
    def __init__(self):
        super(_Logging, self).__init__()
        # NB: The log file name is matched against [a-zA-Z0-9._-]
        self.LOG_FILENAME = 'visualizer.log'
        self.LOGGERS = {
            'MQTTClient':       'INFO',
            'root.aiosqlite':   'INFO',
            'root.asyncio':     'INFO',
        }
        self.formatters.STYLE = '%'
        self.formatters.LOGFILE = \
            '%(asctime)s %(levelname)s %(name)s: %(message)s'
        self.formatters.STDERR = \
                        '%(levelname)s %(name)s: %(message)s'

# Accept defaults for other logging


class _Database (ConfigLoadable):
    def __init__(self):
        self.FILENAME = '/var/lib/pyde1/pyde1.sqlite3'


config = Config()


#
# "Temporarily" repeated and modified here
#
async def async_queue_get(from_queue: queue.Queue):
    loop = asyncio.get_running_loop()
    done = False
    data = None  # For exit on shutdown
    while not done and not sm.shutdown_underway.is_set():
        try:
            data = await loop.run_in_executor(
                None,
                from_queue.get, True, 1.0)
                            # blocking, timeout
            done = True
        except queue.Empty:
            pass
    if sm.shutdown_underway.is_set():
        logger.info("Shut down async_queue_get")
    return data


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

    topic_upload = f"{config.mqtt.TOPIC_ROOT}/VisualizerUpload"

    payload = sci._asdict()
    payload['url'] = url
    payload['success'] = success

    client.publish(
        topic=topic_upload,
        payload=json.dumps(payload),
        retain=True
    )


def configure_mqtt() -> mqtt.Client:
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

    topic_states = f"{config.mqtt.TOPIC_ROOT}/StateUpdate"
    topic_gates = f"{config.mqtt.TOPIC_ROOT}/SequencerGateNotification"

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        logger_mqtt.debug(f"MQTT Connect: flags: {flags}, "
                          f"reasonCode: {reasonCode}, properties {properties}")
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

            # Note: Gate notifications slightly lag state-change times
            #       as they are the time of Event().set(),
            #       and don't take the time from another notification

            elif not userdata['in_sequence']:
                if name == SequencerGateName.GATE_SEQUENCE_START.value \
                        and active_state == API_MachineStates.Espresso.name:
                    userdata['in_sequence'] = True
                    userdata['sequence_id'] = sequence_id
                    userdata['flow_start'] = 0
                    userdata['pour_start'] = 0
                    userdata['flow_end'] = 0
                    logger.info(f"Sequence started {sequence_id}")
                else:
                    pass    # Assumes gates arrive in order

            else:   # in a sequence

                if sequence_id != userdata['sequence_id']:
                    logger.error("Unexpected sequence id: "
                              f"got {id}, aborting sequence")
                    userdata['in_sequence'] = False

                if name == SequencerGateName.GATE_FLOW_BEGIN.value:
                    userdata['flow_start'] = event_time
                    logger.info('Flow started')

                elif name == SequencerGateName.GATE_FLOW_END.value:
                    userdata['flow_end'] = event_time
                    logger.info('Flow ended')

                elif name == SequencerGateName.GATE_SEQUENCE_COMPLETE.value:
                    userdata['in_sequence'] = False
                    logger_upload.info('Upload triggered')
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
                    logger.info(
                        f"Queued: Timing: {t_pi:.0f} + {t_pour:.0f} for "
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
                logger.info('Pour start')

        else:
            pass

    mqtt_client = mqtt.Client(
        client_id="{}@{}[{}]".format(
            config.mqtt.CLIENT_ID_PREFIX,
            gethostname(),
            os.getpid(),
        ),
        clean_session=None,  # Required for MQTT5
        userdata=userdata_dict,
        protocol=MQTTv5,
        transport=config.mqtt.TRANSPORT,
    )

    if config.mqtt.TLS:
        mqtt_client.tls_set(ca_certs=config.mqtt.TLS_CA_CERTS,
                            certfile=config.mqtt.TLS_CERTFILE,
                            keyfile=config.mqtt.TLS_KEYFILE,
                            cert_reqs=config.mqtt.TLS_CERT_REQS,
                            tls_version=config.mqtt.TLS_VERSION,
                            ciphers=config.mqtt.TLS_CIPHERS)

    if config.mqtt.USERNAME is not None:
        logger.info(f"Connecting with username '{config.mqtt.USERNAME}'")
        mqtt_client.username_pw_set(
            username=config.mqtt.USERNAME,
            password=config.mqtt.PASSWORD
        )

    if config.mqtt.DEBUG:
        paho_logger = pyDE1.getLogger('paho')
        paho_logger.setLevel(logging.DEBUG)
        mqtt_client.enable_logger(paho_logger)

    mqtt_client.on_connect = on_connect_callback
    mqtt_client.on_message = on_message_callback

    return mqtt_client


def run_mqtt_client_sync(mqtt_client: mqtt.Client):

    mqtt_client.connect(host=config.mqtt.BROKER_HOSTNAME,
                   port=config.mqtt.BROKER_PORT,
                   keepalive=config.mqtt.KEEPALIVE,
                   bind_address="",
                   bind_port=0,
                   clean_start=MQTT_CLEAN_START_FIRST_ONLY,
                   properties=None)

    # "start" returns immediately
    # mqtt_client.loop_start()
    # "forever" returns on exception
    # No other reasonable way to catch, see
    # https://stackoverflow.com/questions/2829329/
    #   catch-a-threads-exception-in-the-caller-thread
    mqtt_client.loop_forever()


async def wait_then_cleanup(client: mqtt.Client):
    logger.debug("Waiting for shutdown_underway to shutdown MQTT")
    await loop.run_in_executor(None, sm.shutdown_underway.wait)
    logger.info("shutdown_underway seen as set")
    client.disconnect()
    logger.info("mqtt.Client.disconnect returned")
    # As of 2021-08, loop_stop() will block and force= is ignored
    client.loop_stop()
    logger.info("mqtt.Client.loop_stop returned, setting cleanup_complete")
    sm.cleanup_complete.set()


async def loop_on_queue(client: mqtt.Client):

    async with aiosqlite.connect(config.database.FILENAME) as db:
        while not sm.shutdown_underway.is_set():
            logger.info("Ready and waiting")
            got: ShotCompleteItem = await async_queue_get(
                from_queue=shot_complete_queue)
            logger.info(f"Queue got: {got}")
            # None gets returned on termination of async_queue_get()
            if got is None:
                if not sm.shutdown_underway.is_set():
                    raise RuntimeError(
                        "async_queue_get() unexpectedly returned None")
                else:
                    break

            if config.visualizer.MIN_FLOW_TIME \
                    and (dt := got.flow_end - got.flow_start) \
                            < config.visualizer.MIN_FLOW_TIME:
                logger.info(f"Not uploading, too short {dt:.1f} < "
                            f"{config.visualizer.MIN_FLOW_TIME} seconds")
                continue

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

            logger.info("About to upload")
            r = await asyncio.get_running_loop().run_in_executor(
                None,
                functools.partial(
                    requests.post,
                    url='https://visualizer.coffee/api/shots/upload',
                    files=fd,
                    auth=HTTPBasicAuth(username=config.visualizer.USERNAME,
                                       password=config.visualizer.PASSWORD)
                ))
            r: requests.Response
            if r.ok:
                d = json.loads(r.text)
                url = f"https:///visualizer.coffee/shots/{d['id']}"
                logger_upload.info(url)
                report_upload(sci=got, url=url, success=True,
                              client=client)
            else:
                logger_upload.error(
                    f"Upload failed: {r.status_code} {r.reason} {r.text}")
                logger_upload.debug(pformat(r))
                report_upload(sci=got, url=None, success=False,
                              client=client)


async def setup_and_run():
    global client   # TODO: This is sort of hack-ish
    client = configure_mqtt()
    loop.create_task(wait_then_cleanup(client))
    mqtt_task = loop.run_in_executor(None, run_mqtt_client_sync, client)
    mqtt_task.add_done_callback(sm.shutdown_if_exception)
    logger.info(f"MQTT run_in_executor started")
    # await asyncio.gather(
    #     mqtt_task,
    await loop_on_queue(client=client)
    #     return_exceptions=True
    # )


if __name__ == '__main__':

    import argparse
    ap = argparse.ArgumentParser(
        description="""Service to upload pyDE1 "shots" to visualizer.coffee
        
        Listens to MQTT announcements of flow and state from pyDE1. 
        When complete, accesses the (local) database for the "shot file" 
        and uploads to visualizer.coffee as well as notifying with URL on 
        {config.mqtt.TOPIC_ROOT}/VisualizerUpload
        
        """
        f"Default configuration file is at {config.DEFAULT_CONFIG_FILE}"
    )
    ap.add_argument('-c', type=str, help='Use as alternate config file')

    args = ap.parse_args()

    pyde1_logging.setup_initial_logger()

    config.load_from_yaml(args.c)

    pyde1_logging.setup_direct_logging(config.logging)
    pyde1_logging.config_logger_levels(config.logging)

    logger = pyDE1.getLogger('Main')

    logger_mqtt = pyDE1.getLogger('MQTT')
    logger_upload = pyDE1.getLogger('Upload')

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.set_exception_handler(sm.exception_handler)
    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    t = loop.create_task(setup_and_run())

    loop.run_forever()
    exit(sm.exit_value)


