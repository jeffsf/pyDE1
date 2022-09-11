"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Deciding no how to handle "global" config is a bit more complicated
for multiprocessing than it is for a single process (with or without threads).

Since each process loads Python, to get the same config values for all processes
they all need to either read the same config file, or create copies of the
"original" for themselves. Using something like a multiprocessing.Manager()
seems excessive, as it is unlikely that the values will change during a run.
Leaving that open for the future makes some sense.

That means that each process will need to be either passed the name of the
config file to be read, or the results of that (and any changes prior to
creation of the child processes). Passing the config instance seems to be
no more complex than passing the file reference.

The config data should be easy to access in each of the modules.
Several options for "singleton" behavior:

1) Use a bare module

Advantages:

    Simple access

        import pyDE1.config as config
        do_something_with(config.section.VALUE)

    Only one instance "guaranteed"

Disadvantages:

    No top-level properties

        Though there may be a way to define them, the @property decorator
        will create a property object, but it doesn't seem useful.

        This is one of the main reasons that the Singleton object is used
        for the primary components of pyDE1 (the other is no dangling instances)


2) Module that defines an instance, refer to the instance

Advantages:

    Simple access

        from pyDE1.config import config
        do_something_with(config.section.VALUE)

Disadvantages:

    It is possible that second instance, disconnected from the "real" one,
    could be generated with config = Config()

3) Subclass Singleton

Advantages:

    Only one instance "guaranteed"

Disadvantages:

    More complex access

        from pyDE1.config import Config
        pointer_to_config = Config()    # At the module or function level
        do_something_with(config.section.VALUE)



"""

import logging
from typing import Optional

import pyDE1
from pyDE1.config_load import ConfigYAML, ConfigLoadable
from pyDE1.pyde1_logging import (
    ConfigLogging, ConfigLoggingFormatters, ConfigLoggingHandlers
)

DEFAULT_CONFIG_FILE = '/usr/local/etc/pyde1/pyde1.conf'

logger = pyDE1.getLogger('Config')


class Config (ConfigYAML):

    DEFAULT_CONFIG_FILE = '/usr/local/etc/pyde1/pyde1.conf'

    def __init__(self):
        super(Config, self).__init__()
        self.bluetooth = _Bluetooth()
        self.database = _Database()
        self.de1 = _DE1()
        self.http = _HTTP(self)    # Calculating timeout needs bluetooth
        self.logging = _Logging()
        self.mqtt = _MQTT()


# This craziness is so pyCharm autocompletes
# Otherwise typing.SimpleNamespace() would be sufficient


class _MQTT (ConfigLoadable):
    def __init__(self):
        self.TOPIC_ROOT = 'pyDE1'
        self.CLIENT_ID_PREFIX = 'pyde1'
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


class _HTTP (ConfigLoadable):
    def __init__(self, parent):
        self.SERVER_HOST = ''
        self.SERVER_PORT = 1234
        self.SERVER_ROOT = '/'
        # adaptive_allonge.json is 7632 bytes
        self.PATCH_SIZE_LIMIT = 16384
        # Seconds, before abandoning the request
        self.ASYNC_TIMEOUT = 1.0
        # Seconds, 20*2 frames + head + tail at ~100 ms each
        self.PROFILE_TIMEOUT = 4.5
        self.FIRMWARE_TIMEOUT = 15  # Seconds for upload and start (~260 kbps)
        self._response_timeout = None

        # If true, don't output nodes that have no value (write-only)
        # or are empty dicts
        # Otherwise math.nan fills in for the missing value
        # As not compliant with RFC 7159, some parsers may fail with NaN
        # although it is permitted by ECMAScript and JavaScript
        # A False setting is intended to be a development/exploration tool
        # This feature be considered as deprecated
        self.PRUNE_EMPTY_NODES = True

        self._parent = parent   # Path to get to bluetooth

    @property
    def RESPONSE_TIMEOUT(self):
        # See pyDE1/dispatcher/implementation.py
        # Right now, single timeout, bounded by scan/connect
        # This is in addition to the timeout in the implementation
        if self._response_timeout:
            retval = self._response_timeout
        else:
            retval = (max((self._parent.bluetooth.SCAN_TIME
                           + self._parent.bluetooth.CONNECT_TIMEOUT
                           + self.ASYNC_TIMEOUT),
                          (self.PROFILE_TIMEOUT
                           + self.ASYNC_TIMEOUT
                           + self._parent.de1.CUUID_LOCK_WAIT_TIMEOUT))
                      + 0.100)
        return retval

    @RESPONSE_TIMEOUT.setter
    def RESPONSE_TIMEOUT(self, value):
        self._response_timeout = value


class _Logging (ConfigLogging):
    def __init__(self):
        super(_Logging, self).__init__()


class _LoggingFormatters (ConfigLoggingFormatters):
    def __init__(self):
        super(_LoggingFormatters, self).__init__()


class _LoggingHandlers (ConfigLoggingHandlers):
    def __init__(self):
        super(_LoggingHandlers, self).__init__()


class _Bluetooth (ConfigLoadable):
    def __init__(self):
        self.SCAN_TIME = 5  # Seconds
        self.CONNECT_TIMEOUT = 10  # Seconds
        self.DISCONNECT_TIMEOUT = 5  # Seconds
        self.SCAN_CACHE_EXPIRY = 300  # Seconds, probably too long
        self.RECONNECT_RETRY_COUNT = 10 # Before using RECONNECT_GAP
        self.RECONNECT_GAP = 10 # Seconds
        # Files that hold the Bluetooth ID of connected devices
        # for potential cleanup by supervisor scripts
        self.ID_FILE_DIRECTORY = '/var/lib/pyde1/'
        self.ID_FILE_SUFFIX = '.btid'


class _Database (ConfigLoadable):
    def __init__(self):
        self.FILENAME = '/var/lib/pyde1/pyde1.sqlite3'
        self.BACKUP_TIMEOUT = 60  # seconds
        self.BACKUP_COMPRESSION_EXECUTABLE = 'xz'


class _DE1 (ConfigLoadable):
    def __init__(self):
        self.LINE_FREQUENCY = 60
        self.MAX_WAIT_FOR_READY_EVENTS = 4.0 # Seconds (28 at 0.1 each)
        self.CUUID_LOCK_WAIT_TIMEOUT = 2 # Seconds
        self.SEQUENCE_WATCHDOG_TIMEOUT = 270 # seconds
        self.DEFAULT_AUTO_OFF_TIME = None   # Minutes
        self.STOP_AT_WEIGHT_ADJUST = -0.07  # Secs, larger increases weight
        self.bump_resist = _BumpResist()
        self.API_STOP_IGNORES_CHECKS = False  # Request Idle in all cases
        self.PATCH_ON_CONNECT = None  # If defined as a dict, PATCH /de1


class _BumpResist (ConfigLoadable):
    def __init__(self):
        # For stop/skip based on weight, try to ignore "bumps"
        # If the estimated weight flow is over the threshold
        # use multiplier * DE1 estimated flow
        self.FLOW_THRESHOLD = 10.0  # g/s
        self.FLOW_MULTIPLIER = 1.1
        self.SUB_MEDIAN_WEIGHT = True  # when excessive flow
        self.USE_MEDIAN_WEIGHT_ALWAYS = False
        self.USE_MEDIAN_FLOW_ALWAYS = False


config = Config()
