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

from socket import gethostname

import os

import pyDE1.config


def run_api_outbound(config: pyDE1.config.Config,
                     log_queue: multiprocessing.Queue,
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

    from pyDE1.supervise import SupervisedTask
    import pyDE1.shutdown_manager as sm

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    logger = logging.getLogger(multiprocessing.current_process().name)

    initialize_default_logger(log_queue)
    set_some_logging_levels()
    config.set_logging()

    client_logger = logging.getLogger('MQTTClient')
    client_logger.level = logging.INFO

    # https://github.com/eclipse/paho.mqtt.c/issues/864
    # Add support for Unix-domain sockets #864 (open issue)

    # MQTT_PROTOCOL_VERSION = asyncio_mqtt.client.ProtocolVersion.V5

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    # signal.signal(signal.SIGHUP, signal.SIG_IGN)

    # TODO: THIS NEEDS TO BE TRIGGERED FROM MAIN PROCESS

    def on_shutdown_underway_cleanup():
        logger.info("Shutdown wait beginning")
        sm.shutdown_underway.wait()
        logger.info("Shutting down MQTT client")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("Setting cleanup_complete")
        sm.cleanup_complete.set()

    on_shutdown_wait_task = loop.run_in_executor(
        None, on_shutdown_underway_cleanup)

    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    loop.set_exception_handler(sm.exception_handler)

    async def heartbeat():
        import random
        while not sm.shutdown_underway.is_set():
            await asyncio.sleep(10)
            logger.debug("===== BEEP =====")

    heartbeat_task = SupervisedTask(heartbeat)


    def on_log_callback(client: mqtt.Client, userdata, level, buf):
        client_logger.info(f"CB: Log: level: {level} '{buf}' ({type(buf)})")

    def _start_shutdown(sig = None):
        loop.create_task(sm.shutdown(sig, loop))

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        if reasonCode == 0:
            level = logging.INFO
        else:
            level = logging.ERROR
        client_logger.log(level,
            f"CB: Connect: flags: {flags}, reasonCode: {reasonCode}, "
            f"properties {properties}")
        if reasonCode != 0:
            client_logger.critical(
                f"Connection to MQTT broker failed: {str(reasonCode)}, "
                "initiating process shutdown." )
            loop.call_soon_threadsafe(_start_shutdown)

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
        client_id="{}@{}[{}]".format(
            config.mqtt.CLIENT_ID_PREFIX,
            gethostname(),
            os.getpid(),
        ),
        clean_session=None,  # Required for MQTT5
        userdata=None,
        protocol=MQTTv5,
        transport=config.mqtt.TRANSPORT,
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

    if config.mqtt.USERNAME is not None:
        logger.info(f"Connecting with username '{config.mqtt.USERNAME}'")
        mqtt_client.username_pw_set(
            username=config.mqtt.USERNAME,
            password=config.mqtt.PASSWORD
        )

    mqtt_client.connect(host=config.mqtt.BROKER_HOSTNAME,
                        port=config.mqtt.BROKER_PORT,
                        keepalive=config.mqtt.KEEPALIVE,
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
            topic = f"{config.mqtt.TOPIC_ROOT}/{item_as_dict['class']}"
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
                logger.debug(counts)
                counts = {}
                last_update = now

        return outbound_pipe_reader

    loop.add_reader(outbound_pipe.fileno(), create_pipe_reader())

    loop.run_forever()
