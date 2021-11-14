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

import enum
import multiprocessing
import multiprocessing.connection as mpc

import pyDE1.config


class OutboundMode (enum.Enum):
    EventPayload = enum.auto()
    LogRecord = enum.auto()


# See will_topic, below
class MQTTStatusText (enum.Enum):
    on_connection = 'Here'
    on_graceful_disconnect = 'Gone'
    on_will = 'Died'


def run_mqtt_outbound(config: pyDE1.config.Config,
                      log_queue: multiprocessing.Queue,
                      outbound_pipe: mpc.Connection,
                      mode: OutboundMode):

    import asyncio
    import json
    import logging
    import os
    import time

    from collections import Callable
    from socket import gethostname

    import paho.mqtt.client as mqtt
    from paho.mqtt.client import MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

    import pyDE1.pyde1_logging as pyde1_logging
    import pyDE1.shutdown_manager as sm

    from pyDE1.supervise import SupervisedTask

    if mode == OutboundMode.LogRecord:
        logger = pyDE1.getLogger('LogMQTT')
        will_subtopic = 'logging'
    else:
        logger = pyDE1.getLogger('Outbound')
        will_subtopic = 'notification'

    will_topic = "/".join((
        config.mqtt.TOPIC_ROOT, 'status/mqtt', will_subtopic,
    ))

    pyde1_logging.setup_queue_logging(config.logging, log_queue)
    pyde1_logging.config_logger_levels(config.logging)

    client_logger = logger.getChild('MQTTClient')
    client_logger.level = logging.INFO

    # https://github.com/eclipse/paho.mqtt.c/issues/864
    # Add support for Unix-domain sockets #864 (open issue)

    # MQTT_PROTOCOL_VERSION = asyncio_mqtt.client.ProtocolVersion.V5

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    def on_shutdown_underway_cleanup():
        logger.info("Watching for shutdown event")
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

    def _start_shutdown(sig = None):
        loop.create_task(sm.shutdown(sig, loop))

    async def heartbeat():
        hlog = pyDE1.getLogger(
            f"Heartbeat.{multiprocessing.current_process().name}")
        while not sm.shutdown_underway.is_set():
            await asyncio.sleep(10)
            hlog.debug("===== BEEP =====")

    heartbeat_task = SupervisedTask(heartbeat)

    def on_log_callback(client: mqtt.Client, userdata, level, buf):
        client_logger.info(f"CB: Log: level: {level} '{buf}' ({type(buf)})")

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        if reasonCode == 0:
            level = logging.INFO
        else:
            level = logging.ERROR
        client_logger.log(level,
            f"CB: Connect: flags: {flags}, reasonCode: {reasonCode}, "
            f"properties {properties}")
        # Split "action" from logging for clarity
        if reasonCode == 0:
            _send_on_connection_status()
        else:
            client_logger.critical(
                f"Connection to MQTT broker failed: {str(reasonCode)}, "
                "initiating process shutdown." )
            loop.call_soon_threadsafe(_start_shutdown)

    def _send_on_connection_status():
        mqtt_client.publish(
            topic=will_topic,
            payload=MQTTStatusText.on_connection.value,
            qos=0,
            retain=True,
        )

    def _send_on_graceful_disconnect():
        logger.info("Publishing graceful disconnect status")
        rc = mqtt_client.publish(
            topic=will_topic,
            payload=MQTTStatusText.on_graceful_disconnect.value,
            qos=0,
            retain=True,
        )
        rc.wait_for_publish()

    class ClientSendsGracefulDisconnect (mqtt.Client):

        def disconnect(self, *args, **kwargs):
            _send_on_graceful_disconnect()
            super(ClientSendsGracefulDisconnect,
                  self).disconnect(*args, **kwargs)

    def on_publish_callback(client, userdata, mid):
        client_logger.debug(f"CB: Published: mid: {mid}")

    # Caught exception in on_disconnect:
    #     on_disconnect_callback() missing 1 required positional argument:
    #         'properties'
    def on_disconnect_callback(client, userdata, reasonCode, properties=None):
        if sm.shutdown_underway.is_set():
            level = logging.INFO
        else:
            level = logging.ERROR
        client_logger.log(level, f"CB: Disconnect: reasonCode: {reasonCode}, "
                                 f"properties {properties}")

    def on_socket_open_callback(client, userdata, socket):
        client_logger.debug(f"CB: Socket open: socket: {socket}")

    def on_socket_close_callback(client, userdata, socket):
        client_logger.debug(f"CB: Socket close: socket: {socket}")

    def on_socket_register_write_callback(client, userdata, socket):
        client_logger.debug(f"CB: Socket register write: socket: {socket}")

    def on_socket_unregister_write_callback(client, userdata, socket):
        client_logger.debug(f"CB: Socket unregister write: socket: {socket}")

    mqtt_client = ClientSendsGracefulDisconnect(
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

    mqtt_client.will_set(topic=will_topic,
                         payload=MQTTStatusText.on_will.value,
                         qos=0,
                         retain=True,
                         properties=None
                         )

    if config.mqtt.TLS:
        mqtt_client.tls_set(ca_certs=config.mqtt.TLS_CA_CERTS,
                            certfile=config.mqtt.TLS_CERTFILE,
                            keyfile=config.mqtt.TLS_KEYFILE,
                            cert_reqs=config.mqtt.TLS_CERT_REQS,
                            tls_version=config.mqtt.TLS_VERSION,
                            ciphers=config.mqtt.TLS_CIPHERS)

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

    def create_pipe_reader_event_payload() -> Callable:

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
                # retain=True,  # Can cause client to always check if "current"
                retain=False,
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

    def create_pipe_reader_log_record() -> Callable:

        def outbound_pipe_reader():

            nonlocal last_update, update_period, counts
            nonlocal outbound_pipe, mqtt_client

            record: logging.LogRecord = outbound_pipe.recv()

            mqtt_client.publish(
                topic=f"{config.mqtt.TOPIC_ROOT}/log",
                payload=record.getMessage(),
                qos=0,
                retain=False,
                properties=None
            )

            record_as_json = pyde1_logging.log_record_to_json(record)
            mqtt_client.publish(
                topic=f"{config.mqtt.TOPIC_ROOT}/log/record",
                payload=record_as_json,
                qos=0,
                retain=False,
                properties=None
            )

        return outbound_pipe_reader

    if mode == OutboundMode.LogRecord:
        reader = create_pipe_reader_log_record()
    else:
        reader = create_pipe_reader_event_payload()

    loop.add_reader(outbound_pipe.fileno(), reader)

    loop.run_forever()
