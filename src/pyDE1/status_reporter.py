"""
Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import logging
import multiprocessing
import os
from socket import gethostname

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

import pyDE1
import pyDE1.shutdown_manager as sm
from pyDE1.config import config
from pyDE1.api.outbound.mqtt.run import MQTTStatusText

def attach(subtopic: str,
           loop: asyncio.AbstractEventLoop,
           logger: logging.Logger = None):

    try:
        pname = multiprocessing.current_process().name
    except AttributeError:
        pname = __name__
    if logger is None:
        logger = pyDE1.getLogger(pname)

    client_logger = logger.getChild('MQTTClient')
    client_logger.setLevel(logging.INFO)

    will_topic = config.mqtt.TOPIC_ROOT + '/' + subtopic

    class ClientSendsGracefulDisconnect (mqtt.Client):

        def disconnect(self, *args, **kwargs):
            _send_on_graceful_disconnect()
            super(ClientSendsGracefulDisconnect,
                  self).disconnect(*args, **kwargs)

    mqtt_client = ClientSendsGracefulDisconnect(
        client_id="{}@{}[{}]{}".format(
            config.mqtt.CLIENT_ID_PREFIX,
            gethostname(),
            os.getpid(),
            pname,
        ),
        clean_session=None,  # Required for MQTT5
        userdata=None,
        protocol=MQTTv5,
        transport=config.mqtt.TRANSPORT,
    )

    def _send_on_connection():
        client_logger.info(
            f"Publishing {will_topic} {MQTTStatusText.on_connection.value}")
        mqtt_client.publish(
            topic=will_topic,
            payload=MQTTStatusText.on_connection.value,
            qos=0,
            retain=True,
        )

    def _send_on_graceful_disconnect():
        client_logger.info(
            f"Publishing {will_topic}  {MQTTStatusText.on_graceful_disconnect.value}")
        rc = mqtt_client.publish(
            topic=will_topic,
            payload=MQTTStatusText.on_graceful_disconnect.value,
            qos=0,
            retain=True,
        )
        rc.wait_for_publish()

    def on_connect_callback(client, userdata, flags, reasonCode, properties):
        client_logger.log(logging.INFO if reasonCode == 0
                          else logging.ERROR,
                          f"CB: Connect: flags: {flags}, reasonCode: {reasonCode}, "
                          f"properties {properties}")
        if reasonCode == 0:
            _send_on_connection()
        else:
            client_logger.critical(
                f"Connection to MQTT broker failed: {str(reasonCode)}, ")
            # loop.call_soon_threadsafe(_start_shutdown)

    def on_disconnect_callback(client, userdata, reasonCode, properties=None):
        if sm.shutdown_underway.is_set():
            level = logging.INFO
        else:
            level = logging.ERROR
        client_logger.log(level, f"CB: Disconnect: reasonCode: {reasonCode}, "
                                 f"properties {properties}")

    mqtt_client.on_connect = on_connect_callback
    mqtt_client.on_disconnect = on_disconnect_callback
    mqtt_client.enable_logger(client_logger)

    if config.mqtt.USERNAME is not None:
        logger.info(f"Connecting MQTT with username '{config.mqtt.USERNAME}'")
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

    async def cleanup_on_shutdown():
        # "Independent" shutdown for potential extraction
        client_logger.info("Watching for shutdown event")
        await sm.wait_for_shutdown_underway()
        client_logger.info("Shutting down MQTT client")
        if mqtt_client.is_connected():
            mqtt_client.disconnect()
        mqtt_client.loop_stop()
        client_logger.info("MQTT loop stopped")
        # This is a secondary process, don't set "done"

    loop.create_task(cleanup_on_shutdown())

    mqtt_client.connect(host=config.mqtt.BROKER_HOSTNAME,
                        port=config.mqtt.BROKER_PORT,
                        keepalive=config.mqtt.KEEPALIVE,
                        bind_address="",
                        bind_port=0,
                        clean_start=MQTT_CLEAN_START_FIRST_ONLY,
                        properties=None)

    mqtt_client.loop_start()


