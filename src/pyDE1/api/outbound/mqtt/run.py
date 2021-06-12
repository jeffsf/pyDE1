"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

"Null" outbound processor that just keeps the queue clear,
counting the various messages by type,
logging every update_period seconds (and resetting the count)
"""


# Only import the minimal here, as it potentially ends up in all processes.
import multiprocessing, multiprocessing.connection

# TODO: look into how loggers here relate to the root logger from "main"

# TODO: Look into or resolve processes' loggers writing over each other


def run_api_outbound(api_outbound_queue: multiprocessing.Queue):

    import logging
    import os
    import time

    from socket import gethostname

    logger = logging.getLogger(multiprocessing.current_process().name)

    import asyncio
    import json
    import sys

    # cpn = multiprocessing.current_process().name
    # for k in sys.modules.keys():
    #     if (k.startswith('pyDE1')
    #             or k.startswith('bleak')
    #             or k.startswith('asyncio-mqtt')):
    #         print(
    #             f"{cpn}: {k}"
    #         )

    import asyncio_mqtt
    import asyncio_mqtt.client

    # https://github.com/eclipse/paho.mqtt.c/issues/864
    # Add support for Unix-domain sockets #864 (open issue)

    # TODO: Move these into a settings object

    MQTT_TOPIC_ROOT = 'pyDE1'

    MQTT_CLIENT_ID = f"pyDE1@{gethostname()}[{os.getpid()}]"

    MQTT_BROKER_HOSTNAME = '::'
    MQTT_BROKER_PORT = 1883

    MQTT_TRANSPORT = 'tcp'
    MQTT_TLS_CONTEXT = None
    MQTT_KEEPALIVE = 60

    MQTT_USERNAME = None
    MQTT_PASSWORD = None

    MQTT_PROTOCOL_VERSION = asyncio_mqtt.client.ProtocolVersion.V5

    async def run(api_outbound_queue: multiprocessing.Queue):

        last_update = time.time()
        update_period = 10  # in seconds
        counts = {}

        async with asyncio_mqtt.client.Client(
            hostname=MQTT_BROKER_HOSTNAME,
            port=MQTT_BROKER_PORT,
            transport=MQTT_TRANSPORT,
            tls_context=MQTT_TLS_CONTEXT,
            keepalive=MQTT_KEEPALIVE,
            protocol=MQTT_PROTOCOL_VERSION,
            username=MQTT_USERNAME,
            password=MQTT_PASSWORD,
            will=None,
            client_id=MQTT_CLIENT_ID,
        ) as client:

            logger.info("Connecting to client")
            asyncio.run_coroutine_threadsafe(client.connect(),
                                             asyncio.get_running_loop())
            logger.info("Client connected")

            while True:
                item_json = api_outbound_queue.get()
                item_as_dict = json.loads(item_json)
                topic = f"{MQTT_TOPIC_ROOT}/{item_as_dict['class']}"
                await client.publish(
                    topic=topic,
                    payload=item_json,
                    qos=0,              # 0: At most once
                    retain=True,        # Always have "last known" available
                    properties=None,    # MQTT 5 only
                )
                now = time.time()
                try:
                    counts[item_as_dict['class']] += 1
                except KeyError:
                    counts[item_as_dict['class']] = 1
                if now - last_update > update_period:
                    logger.info(counts)
                    counts = {}
                    last_update = now

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    # loop.run_until_complete(run(api_outbound_queue=api_outbound_queue))
    loop.run_until_complete(run(api_outbound_queue=api_outbound_queue))
