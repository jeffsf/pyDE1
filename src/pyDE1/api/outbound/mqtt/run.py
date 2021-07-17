"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

"Null" outbound processor that just keeps the queue clear,
counting the various messages by type,
logging every update_period seconds (and resetting the count)
"""

# Supervise:
#   nothing: loop.add_reader()

# Only import the minimal here, as it potentially ends up in all processes.
import multiprocessing
import multiprocessing.connection as mpc

# TODO: look into how loggers here relate to the root logger from "main"

# TODO: Look into or resolve processes' loggers writing over each other


def run_api_outbound(log_queue: multiprocessing.Queue,
                     outbound_pipe: mpc.Connection):

    import logging
    import multiprocessing
    import time
    import asyncio
    import json
    import signal

    from collections import Callable

    import paho.mqtt.client as mqtt
    from paho.mqtt.client import MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

    from pyDE1.utils import cancel_tasks_by_name
    from pyDE1.signal_handlers import add_handler_shutdown_signals
    from pyDE1.supervise import SupervisedTask

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    from pyDE1.config.mqtt import MQTT_TOPIC_ROOT, MQTT_CLIENT_ID, \
        MQTT_BROKER_HOSTNAME, MQTT_BROKER_PORT, MQTT_TRANSPORT, \
        MQTT_TLS_CONTEXT, MQTT_KEEPALIVE, MQTT_USERNAME, MQTT_PASSWORD

    logger = logging.getLogger(multiprocessing.current_process().name)

    initialize_default_logger(log_queue)
    set_some_logging_levels()

    client_logger = logging.getLogger('MQTTClient')
    client_logger.level = logging.INFO

    # https://github.com/eclipse/paho.mqtt.c/issues/864
    # Add support for Unix-domain sockets #864 (open issue)

    # MQTT_PROTOCOL_VERSION = asyncio_mqtt.client.ProtocolVersion.V5

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    async def shutdown_signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        process = multiprocessing.current_process()
        logger = logging.getLogger('MQTTShutdown')
        logger.info(f"{str(signal)} SHUTDOWN INITIATED")
        logger.info("Shutting down MQTT client")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("Shutting down other tasks")
        cancel_tasks_by_name('', starts_with=True)
        logger.info("Stopping loop")
        loop.stop()
        logger.info("Loop stopped, closing this process")
        # AttributeError: 'NoneType' object has no attribute 'kill'
        # multiprocessing.current_process().kill()
        multiprocessing.current_process().close()
        logger.info("Process closed")

    add_handler_shutdown_signals(shutdown_signal_handler)

    async def heartbeat():
        import random
        while True:
            await asyncio.sleep(10)
            if random.choice((True, False)):
                logger.info("===== BEEP =====")
            else:
                logger.info("===== BEEP =====")
                # logger.info("XXXXX BYE XXXXX")
                # raise RuntimeError("Roll of the dice")

    SupervisedTask(heartbeat)


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

    mqtt_client.connect(host=MQTT_BROKER_HOSTNAME,
                   port=MQTT_BROKER_PORT,
                   keepalive=MQTT_KEEPALIVE,
                   bind_address="",
                   bind_port=0,
                   clean_start=MQTT_CLEAN_START_FIRST_ONLY,
                   properties=None)

    mqtt_client.loop_start()

    last_update = time.time()
    update_period = 10  # in seconds
    counts = {}

    def create_pipe_reader() -> Callable:

        def outbound_pipe_reader():

            nonlocal last_update, update_period, counts
            nonlocal outbound_pipe, mqtt_client

            item_json = outbound_pipe.recv()
            item_as_dict = json.loads(item_json)
            topic = f"{MQTT_TOPIC_ROOT}/{item_as_dict['class']}"
            mqtt_client.publish(
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

        return outbound_pipe_reader

    loop.add_reader(outbound_pipe.fileno(), create_pipe_reader())

    loop.run_forever()
