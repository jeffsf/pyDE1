"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import logging
import multiprocessing
import os

from _socket import gethostname

from paho.mqtt import client as mqtt
from paho.mqtt.client import MQTTv5, MQTT_CLEAN_START_FIRST_ONLY

from pyDE1.config import config


def send_single_message(subtopic: str, msg: str,
                        logger: logging.Logger):

    client_logger = logger.getChild('MQTTClient')
    client_logger.setLevel(logging.INFO)

    try:
        pname = multiprocessing.current_process().name
    except AttributeError:
        pname = __name__

    mqtt_client = mqtt.Client(
        client_id="{}@{}[{}]{}_ssm".format(
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

    if config.mqtt.USERNAME is not None:
        logger.info(f"Connecting MQTT with username '{config.mqtt.USERNAME}'")
        mqtt_client.username_pw_set(
            username=config.mqtt.USERNAME,
            password=config.mqtt.PASSWORD
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

    mqtt_client.publish(
        config.mqtt.TOPIC_ROOT + '/' + subtopic,
        msg,
        qos=0,
        retain=True,
    )

    mqtt_client.disconnect()