"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Collected configuration parameters
"""

import os
import socket

MQTT_TOPIC_ROOT = 'pyDE1'
MQTT_CLIENT_ID = f"pyDE1@{socket.gethostname()}[{os.getpid()}]"
MQTT_BROKER_HOSTNAME = '::'
MQTT_BROKER_PORT = 1883
MQTT_TRANSPORT = 'tcp'
MQTT_TLS_CONTEXT = None
MQTT_KEEPALIVE = 60
MQTT_USERNAME = None
MQTT_PASSWORD = None
