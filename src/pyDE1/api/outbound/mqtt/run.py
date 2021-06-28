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
import multiprocessing

# TODO: look into how loggers here relate to the root logger from "main"

# TODO: Look into or resolve processes' loggers writing over each other
from queue import Empty


def run_api_outbound(api_outbound_queue: multiprocessing.Queue):

    import logging
    import os
    import time

    from socket import gethostname

    logger = logging.getLogger(multiprocessing.current_process().name)

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    initialize_default_logger()
    set_some_logging_levels()

    client_logger = logging.getLogger('MQTTClient')
    client_logger.level = logging.INFO

    import asyncio
    import json
    import sys
    import signal

    # cpn = multiprocessing.current_process().name
    # for k in sys.modules.keys():
    #     if (k.startswith('pyDE1')
    #             or k.startswith('bleak')
    #             or k.startswith('asyncio-mqtt')):
    #         print(
    #             f"{cpn}: {k}"
    #         )

    # import asyncio_mqtt
    # import asyncio_mqtt.client

    import paho.mqtt.client as mqtt
    from paho.mqtt.client import MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

    from pyDE1.utils import cancel_tasks_by_name

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

    # MQTT_PROTOCOL_VERSION = asyncio_mqtt.client.ProtocolVersion.V5

    _shutdown = False
    QUEUE_GET_TIMEOUT = 0.5  # at 10-20 pps, this seems conservatively long

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    signals = (
        signal.SIGHUP,
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGTERM,
    )

    async def signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        process = multiprocessing.current_process()
        logger = logging.getLogger('MQTTShutdown')
        logger.info(f"{str(signal)} SHUTDOWN INITIATED")
        graceful_shutdown()

    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda sig=sig: asyncio.create_task(signal_handler(sig, loop),
                                                name=str(sig)))

    def graceful_shutdown():
        nonlocal _shutdown
        # nonlocal api_outbound_queue
        _shutdown = True
        logger.info("Shutting down MQTT client")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("Shutting down other tasks")
        cancel_tasks_by_name('', starts_with=True)
        logger.info("Stopping loop")
        loop.stop()
        # Queue.close() probably needs to be called by the writer
        # https://docs.python.org/3/library/multiprocessing.html#multiprocessing.Queue.close
        # logger.info("Closing queue")
        # api_outbound_queue.close()
        # api_outbound_queue = None
        logger.info("Loop stopped, closing this process")
        # AttributeError: 'NoneType' object has no attribute 'kill'
        # multiprocessing.current_process().kill()
        multiprocessing.current_process().close()
        logger.info("Process closed")

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            logger.info("===== BEEP =====")

    loop.create_task(heartbeat(), name='Heartbeat')

    def on_log_callback(client: mqtt.Client, userdata, level, buf):
        client_logger.info(f"CB: Log: level: {level} '{buf}' ({type(buf)})")

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        client_logger.info(f"CB: Connect: flags: {flags}, reasonCode: {reasonCode}, "
                    f"properties {properties}")

    def on_publish_callback(client, userdata, mid):
        client_logger.info(f"CB: Published: mid: {mid}")

    # Caught exception in on_disconnect:
    #     on_disconnect_callback() missing 1 required positional argument:
    #         'properties'
    def on_disconnect_callback(client, userdata, reasonCode, properties=None):
        client_logger.info(f"CB: Disconnect: reasonCode: {reasonCode}, "
                    f"properties {properties}")

    def on_socket_open_callback(client, userdata, socket):
        client_logger.info(f"CB: Socket open: socket: {socket}")

    def on_socket_close_callback(client, userdata, socket):
        client_logger.info(f"CB: Socket close: socket: {socket}")

    def on_socket_register_write_callback(client, userdata, socket):
        client_logger.info(f"CB: Socket register write: socket: {socket}")

    def on_socket_unregister_write_callback(client, userdata, socket):
        client_logger.info(f"CB: Socket unregister write: socket: {socket}")

    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        clean_session=None,  # Required for MQTT5
        userdata=None,
        protocol=MQTTv5,
        transport=MQTT_TRANSPORT,
    )

    # mqtt_client.on_log = on_log_callback
    mqtt_client.on_connect = on_connect_callback
    # mqtt_client.on_publish = on_publish_callback
    mqtt_client.on_disconnect = on_disconnect_callback
    mqtt_client.on_socket_open = on_socket_open_callback
    mqtt_client.on_socket_close = on_socket_close_callback
    # mqtt_client.on_socket_register_write = on_socket_register_write_callback
    # mqtt_client.on_socket_unregister_write = on_socket_unregister_write_callback

    mqtt_client.enable_logger(client_logger)

    def pick_and_send(mp_queue: multiprocessing.Queue,
                      client: mqtt.Client):

        client.connect(host=MQTT_BROKER_HOSTNAME,
                       port=MQTT_BROKER_PORT,
                       keepalive=MQTT_KEEPALIVE,
                       bind_address="",
                       bind_port=0,
                       clean_start=MQTT_CLEAN_START_FIRST_ONLY,
                       properties=None)

        client.loop_start()

        last_update = time.time()
        update_period = 10  # in seconds
        counts = {}

        while True:
            try:
                item_json = mp_queue.get(block=True,
                                         timeout=QUEUE_GET_TIMEOUT)
            except Empty:
                if _shutdown:
                    logger.info("Shutdown of MQTT loop requested")
                    return
                else:
                    continue
            except ValueError:
                # queue has been closed
                return

            item_as_dict = json.loads(item_json)
            topic = f"{MQTT_TOPIC_ROOT}/{item_as_dict['class']}"
            client.publish(
                topic=topic,
                payload=item_json,
                qos=0,
                retain=True,
                properties=None
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

    loop.run_in_executor(None, pick_and_send, api_outbound_queue, mqtt_client)

    loop.run_forever()
