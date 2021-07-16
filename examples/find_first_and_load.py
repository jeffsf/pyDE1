"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Since the requests module isn't asyncio aware and the command server
is sequential on how it handles requests, accept blocking on the main
thread and run the MQTT client in its own thread.
"""
from pyDE1.event_manager.events import ConnectivityState

DISCONNECT_AT_END = True


import json
import logging
import os
import queue
import threading
import time

from socket import gethostname
from typing import Optional, NamedTuple

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage, MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

import requests

from pyDE1.dispatcher.resource import Resource, DE1ModeEnum, ConnectivityEnum



format_string = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=logging.DEBUG,
                    format=format_string,
                    )

logger = logging.getLogger('main')
logger_scanner = logging.getLogger('Scanner')
logger_connect = logging.getLogger('Connect')

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


# Utilities for inbound API requests

def path_of(res: Resource):
    return f"http://{SERVER_HOST}:{SERVER_PORT}" \
           f"{os.path.join(SERVER_ROOT, res.value)}"


def show_result(r: requests.Response):
    body = r.request.body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode('utf-8')
    logger.debug(f"{r.status_code} {r.request.method} {r.request.url}\n"
          f"{body}\n{r.text}")


# Specific inbound API requests

def find_first(res: Resource):
    t0 = time.time()
    r = requests.patch(path_of(res),
                       json = {"first_if_found": True})
    t1 = time.time()
    show_result(r)
    logger.debug(f"{res} elapsed time: {(t1 - t0):.3f} seconds")

def connect(res: Resource, id: Optional[str]):
    t0 = time.time()
    r = requests.patch(path_of(res),
                       json = {"id": id})
    t1 = time.time()
    show_result(r)
    logger.debug(f"{res} elapsed time: {(t1 - t0):.3f} seconds")

def upload_profile(filename: str):
    logger.debug(f"cwd: {os.path.abspath(os.curdir)}")
    t0 = time.time()
    with open(filename, 'rb') as profile:
        logger.debug(f"opened: {filename}")
        r = requests.put(path_of(Resource.DE1_PROFILE),
                         data = profile)
    t1 = time.time()
    show_result(r)
    logger.debug(f"Upload profile elapsed time: {(t1 - t0):.3f} seconds")


def set_saw(mass: float):
    r = requests.patch(path_of(Resource.DE1_CONTROL_ESPRESSO),
                       json={"stop_at_time": None,
                             "stop_at_volume": None,
                             "stop_at_weight": mass})
    show_result(r)


def run():

    have_de1 = threading.Event()
    have_scale = threading.Event()

    ready_de1 = threading.Event()
    ready_scale = threading.Event()

    run_start = time.time()

    def check_connectivity(res: Resource,
                           have: threading.Event,
                           ready: threading.Event):
        """
        If already connected, set the "have" event
        If also ready, set the "ready" event
        """
        r = requests.get(path_of(res))
        show_result(r)
        try:
            if r.json()['mode'] == ConnectivityEnum.READY.value:
                have.set()
                ready.set()
            elif r.json()['mode'] == ConnectivityEnum.CONNECTED.value:
                have.set()
                logger.warning("{res} is connected, but not ready")
        finally:
            return


    # Set up the MQTT client

    topic_scanner = f"{MQTT_TOPIC_ROOT}/ScannerNotification"
    topic_connect = f"{MQTT_TOPIC_ROOT}/ConnectivityChange"

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        logger.debug(f"MQTT Connect: flags: {flags}, reasonCode: {reasonCode}, "
              f"properties {properties}")
        client.subscribe(topic_scanner)
        client.subscribe(topic_connect)

    def on_message_callback(client: mqtt.Client, userdata,
                            message: MQTTMessage):

        payload_dict = json.loads(message.payload)

        if message.topic == topic_scanner:
            # Just log for information, as using first_found
            id = payload_dict['id']
            name = payload_dict['name']
            action = payload_dict['action']
            logger_scanner.debug(f"{action}: {name} {id}")

        elif message.topic == topic_connect:
            logger_connect.debug(
                f"{payload_dict['sender']}: {payload_dict['state']}")
            if payload_dict['event_time'] < run_start:
                logger.debug("Skipping retained message")
            else:
                if payload_dict['sender'] == 'DE1':
                    event = ready_de1
                else:  # Right now, it's either a DE1 or a Scale
                    event = ready_scale
                if payload_dict['state'] == ConnectivityState.READY.value:
                    event.set()
                else:
                    event.clear()

        else:
            pass

    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        clean_session=None,  # Required for MQTT5
        userdata=None,
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

    mqtt_client.loop_start()

    check_connectivity(Resource.DE1_CONNECTIVITY, have_de1, ready_de1)
    check_connectivity(Resource.SCALE_CONNECTIVITY, have_scale, ready_scale)

    t0 = time.time()

    if not have_de1.is_set():
        find_first(Resource.DE1_ID)
    if not have_scale.is_set():
        find_first(Resource.SCALE_ID)

    t1 = time.time()
    logger.debug(f"##### Connection time: {(t1 - t0):.3f} seconds")

    ready_de1.wait()

    upload_profile('/home/ble-remote/devel/pyDE1/examples/jmk_eb6.json')
    set_saw(50.0)

    if DISCONNECT_AT_END:
        connect(Resource.SCALE_ID, None)
        connect(Resource.DE1_ID, None)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()

    logger.info("Done")


if __name__ == '__main__':
    run()
