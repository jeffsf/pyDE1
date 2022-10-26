..
    Copyright © 2021 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

========
HTTP API
========

The HTTP API is used to query and change the state of the DE1, scale, and
controller. This API provides a level of abstraction higher than that of the
Bluetooth interface to the DE1. For example, a profile is uploaded through
the API, directly from a JSON v2 file. The caller does not need to know how
that is converted into frames and then loaded over Bluetooth to the DE1.

Most payloads are JSON with status being returned in a REST-like manner
with HTTP error codes. (Profiles and firmware are uploaded verbatim.)

The API has been organized into sections that align with user experience,
rather than paralleling the DE1's low-level API. Users should not have to be
overly concerned about if the functionality is provided by the DE1 firmware,
or by the controller supplied by pyDE1. In some cases, certain firmware
versions are able to control a feature directly with the DE1,
yet others require the controller's interaction. From a caller perspective,
the parameters are set up the same way for both.

------------
API Overview
------------

Principles of Operation
========================

The API is REST-like in operation, with the operation being specified by
the HTTP method. In general

* GET returns information about a resource without modifying it
* PATCH updates some information or state
* PUT sends a complete replacement

At this time, PATCH is used for virtually all changes. Profiles and firmware
images are PUT as they completely replace the proir profile or firmware.

The *InboundAPI* process runs a single-threaded, HTTP server.
It is intentionally sequential in operation as many operations assume that
the initial state is that resulting from completion of all prior operations.
On receiving a request, its URL is compared to the list of valid ``Resource``
values and confirmed that the requested method (GET, PATCH, PUT) is valid for
that resource. If not, an error response is returned. If so, the request
and request body are wrapped in an ``APIRequest`` object and queued
for processing.

In the *Controller* process, a queue watcher retrieves the ``APIRequest``.
This code can be found in ``pyDE1/dispatcher/``.
It evaluates if connectivity to either or both the DE1 and scale is required.
If connectivity requirements are not met, an exception is raised. Like other
exceptions in processing these API requests, they are caught and an error
``APIResponse`` is queued back to the *InboundAPI* process, often including
traceback information.

The ``Resource`` is used as a key into the ``MAPPING`` dict to determine
where the various data values can be accessed, as well as how they are
represented in JSON. Individual elements of the ``MAPPING`` are represented
with an ``IsAt`` object. The ``IsAt`` instance identifies on which object the
setter and getter can be found, the setter and getter, if it is read-only,
write-only, or read/write, as well as the expected data type. The data type
is checked before proceeding.

For most payloads, the JSON structure is then walked, getting or setting values
as requested.

.. note::

  With payloads containing multiple values, a PATCH operation may not be atomic
  if later elements fail after earlier ones have been set.

All operations have a timeout. These timeouts can be seen in the ``Config``,
either in the Bluetooth or HTML sections. Exceeding a timeout results in
an exception being raised.

If no exception has been raised, a success ``APIResponse`` is queued back
to the *InboundAPI* process. If an exception is raised, an error response
is queued.

The *InboundAPI* process then retrieves the ``APIResponse`` and returns
its contents as an HTTP response to the caller.

.. note::

  API consumers should check the response headers to determine if the request
  was sucessful or not.

.. note::

  When changes are made to the DE1's internal registers, an asynchronous
  read-back is usually requested. As it takes roughly 100 ms per transaction
  over Bluetooth with the current DE1 hardware and its Bluetooth firmware,
  a read over the API may not yet be updated when the setting API call returns.

  While tempting to assume that the data in the DE1 is that which was written,
  there are certain registers that trim or reject values out of range, or round
  them slightly differently internally.

Example Responses
-----------------

A sucessful setting change

.. code-block::

  $ curl -D - -X PATCH --data '{ "start_fill_level": 0 }' http://localhost:1234/de1/setting/start_fill_level
  HTTP/1.0 200 OK
  Server: BaseHTTP/0.6 Python/3.9.2
  Date: Tue, 16 Nov 2021 21:37:09 GMT
  Content-type: application/json
  Content-length: 3
  Last-Modified: Tue, 16 Nov 2021 13:37:09 -0800

  []


An "early" error response due to an inappropriate method

.. code-block::

  $ curl -D - -X PUT --data '{ "start_fill_level": 0 }' http://localhost:1234/de1/setting/start_fill_level
  HTTP/1.0 501 Not Implemented
  Server: BaseHTTP/0.6 Python/3.9.2
  Date: Tue, 16 Nov 2021 21:37:56 GMT
  Content-type: text/plain
  Content-length: 63
  Last-Modified: Tue, 16 Nov 2021 13:37:56 -0800

  PUT not yet supported for Resource.DE1_SETTING_START_FILL_LEVEL

An error response due to a "bad" value

.. code-block::

  $ curl -D - -X PATCH --data '{ "start_fill_level": "0.0" }' http://localhost:1234/de1/setting/start_fill_level
  HTTP/1.0 400 Bad Request
  Server: BaseHTTP/0.6 Python/3.9.2
  Date: Tue, 16 Nov 2021 21:39:44 GMT
  Content-type: text/plain
  Content-length: 67
  Last-Modified: Tue, 16 Nov 2021 13:39:44 -0800

  DE1APITypeError('Expected int value at start_fill_level:, not 0.0')

An error response due to malformed JSON

.. code-block::

  $ curl -D - -X PATCH --data '{ start_fill_level: 0.0 }' http://localhost:1234/de1/setting/start_fill_level
  HTTP/1.0 400 Bad Request
  Server: BaseHTTP/0.6 Python/3.9.2
  Date: Tue, 16 Nov 2021 21:42:23 GMT
  Content-type: text/plain
  Content-length: 94
  Last-Modified: Tue, 16 Nov 2021 13:42:23 -0800

  JSONDecodeError('Expecting property name enclosed in double quotes: line 1 column 3 (char 2)'

An error response with traceback

.. code-block::

  $ curl -D - http://localhost:1234/de1
  HTTP/1.0 409 Conflict
  Server: BaseHTTP/0.6 Python/3.9.2
  Date: Tue, 16 Nov 2021 21:44:46 GMT
  Content-type: text/plain
  Content-length: 395
  Last-Modified: Tue, 16 Nov 2021 13:44:46 -0800

  Traceback (most recent call last):
    File "/home/pyde1/deploy/pyde1-devel/src/pyDE1/dispatcher/dispatcher.py", line 120, in _request_queue_processor
      _check_connectivity(got)
    File "/home/pyde1/deploy/pyde1-devel/src/pyDE1/dispatcher/dispatcher.py", line 96, in _check_connectivity
      raise DE1NotConnectedError("DE1 not connected")
  pyDE1.exceptions.DE1NotConnectedError: DE1 not connected


Versioning
==========

The list of resources that can be accessed is defined in
``pyDE1/dispatcher/resource.py`` The list of resources is versioned, as is
the mapping of those resources to data elements found in
``pyDE1/dispatcher/mapping.py``.

The versions of the API (and other components) can be easily retrieved

.. code-block::

  $ curl http://localhost:1234/version
  {
      "mapping_version": "4.0.0",
      "module_versions": {
          "aiosqlite": "0.17.0",
          "asyncio-mqtt": null,
          "bleak": "0.13.0",
          "paho-mqtt": "1.6.1",
          "pyDE1": "0.9.1"
      },
      "platform": "linux",
      "python": "3.9.2 (default, Feb 28 2021, 17:03:44) \n[GCC 10.2.1 20210110]",
      "python_info": {
          "major": 3,
          "micro": 2,
          "minor": 9,
          "releaselevel": "final",
          "serial": 0
      },
      "resource_version": "3.4.0"
  }

Feature Availability
====================

In addition to the software versions, the firmware version and hardware present
on the DE1 can be important to clients.

Rather than requiring each client to keep a list of which firmware provides
which features, *feature flags* are provided in an easily digested form.

.. code-block::

  $ curl http://localhost:1234/de1/feature_flags
  {
      "feature_flags": {
          "fw_version": 1283,
          "ghc_active": true,
          "hot_water_flow_control": false,
          "last_mmr0x80": 14412,
          "max_shot_press": false,
          "mmr_pref_ghc_mci": false,
          "rinse_control": true,
          "safe_to_read_mmr_continuous": true,
          "skip_to_next": true
      }
  }

``ghc_active`` can be used to determine if the commands to start flow
have been disabled or not.

Features introduced prior to firmware version 1250 (April 2020)
are not captured.

--------
Examples
--------

Connect
=======

To First-Found DE1
------------------

.. code-block::

  $ curl -X PATCH --data '{"id": "scan"}' http://localhost:1234/de1/id
  [
      "D9:B2:48:AA:BB:CC"
  ]

To Specific DE1
---------------

.. code-block::

  $ curl -X PATCH --data '{"id": "D9:B2:48:AA:BB:CC"}' http://localhost:1234/de1/id
  []

For further details on scanning, see :doc:`bluetooth_scanning`

Espresso Control
================

.. code-block::

  $ curl http://localhost:1234/de1/control/espresso
  {
      "disable_auto_tare": false,
      "first_drops_threshold": 0.0,
      "last_drops_minimum_time": 3.0,
      "profile_can_override_stop_limits": false,
      "profile_can_override_tank_temperature": true,
      "stop_at_time": null,
      "stop_at_volume": null,
      "stop_at_weight": 46
  }

  $ curl -X PATCH --data '{ "stop_at_weight": 51 }' http://localhost:1234/de1/control/espresso
  []

Query Current State
===================

Although state *updates* are available through MQTT, the DE1 won't report state
until it changes. A newly connected DE1 or client may need current state
information to initialize.

.. code-block::

  $ curl http://localhost:1234/de1/state
  {
    "state": {
        "state": "Sleep",
        "substate": "NoState"
    }
  }

Change Profile
==============

.. code-block::

  $ curl -X PUT --data '{"id": "3f8d1e22d77d860d53d011b4974720974d5380f2"}' http://localhost:1234/de1/profile/id
  []

Upload Profile
==============

Note that the profile's source file is delivered verbatim.

.. code-block::

  $ curl -X PUT --data @./defaultish_88.json http://localhost:1234/de1/profile
  []

List and Fetch Logs
===================

.. code-block::

  $ curl http://localhost:1234/logs
  [
      {
          "atime": 1632985202.3721957,
          "ctime": 1637049601.4134495,
          "id": "pyde1.log.46.gz",
          "mtime": 1633041788.1226397,
          "name": "pyde1.log.46.gz",
          "size": 9125
      },
      {
          "atime": 1636095601.4804242,
          "ctime": 1637049601.4454553,
          "id": "visualizer.log.11.gz",
          "mtime": 1636125920.634909,
          "name": "visualizer.log.11.gz",
          "size": 417
      },

      // similar entries omitted

      {
          "atime": 1636358402.1129558,
          "ctime": 1637049601.4134495,
          "id": "pyde1.log.8.gz",
          "mtime": 1636413162.628252,
          "name": "pyde1.log.8.gz",
          "size": 6525
      }
  ]

Fetch is by ``id``
(which presently is the file name, though this is not guaranteed)

.. code-block::

    $ curl http://localhost:1234/log/pyde1.log 2>/dev/null | tail
    2021-11-16 10:44:55,153 INFO [Controller] DE1.CUUID.FrameWrite.Write: Frame #2 CtrlP,DontCompare,DC_LT,DC_CompP,TBasketTemp,DontInterpolate,IgnoreLimit SetVal: 8.0 Temp: 88.0 Len: 4.0 Trigger: 0 MaxVol: 0.0
    2021-11-16 10:44:55,245 INFO [Controller] DE1.CUUID.FrameWrite.Write: Frame #3 CtrlP,DontCompare,DC_LT,DC_CompP,TBasketTemp,Interpolate,IgnoreLimit SetVal: 4.0 Temp: 88.0 Len: 40.0 Trigger: 0 MaxVol: 0.0
    2021-11-16 10:44:55,343 INFO [Controller] DE1.CUUID.FrameWrite.Write: Frame #4 Limit: 0 ignore_pi: True
    2021-11-16 10:44:55,446 INFO [Controller] Database.Insert: Profile 68e02cd99418003806d8e5efdf711f078bdfcc22 already in profile table.
    2021-11-16 10:44:55,455 INFO [Controller] DE1: Returned from db insert
    2021-11-16 10:44:55,460 INFO [InboundAPI] Inbound.HTTP: 603 200 "OK" - PUT /de1/profile HTTP/1.1 127.0.0.1
    2021-11-16 10:46:49,993 INFO [InboundAPI] Inbound.HTTP: Request: GET /logs HTTP/1.1
    2021-11-16 10:46:50,002 INFO [InboundAPI] Inbound.HTTP: 9 200 "OK" - GET /logs HTTP/1.1 127.0.0.1
    2021-11-16 10:48:33,043 INFO [InboundAPI] Inbound.HTTP: Request: GET /log/pyde1.log HTTP/1.1
    2021-11-16 10:48:33,044 INFO [InboundAPI] Inbound.HTTP: 2 200 "OK" - GET /log/pyde1.log HTTP/1.1 127.0.0.1

Get "Everything"
================

.. note::

    Although this is possible and useful for reference, targeted requests
    are strongly suggested.

.. code-block::

  $ curl http://localhost:1234/de1
  {
      "calibration": {
          "flow_multiplier": {
              "multiplier": 1.0
          },
          "line_frequency": {
              "hz": 60
          }
      },
      "connectivity": {
          "mode": "ready"
      },
      "control": {
          "espresso": {
              "disable_auto_tare": false,
              "first_drops_threshold": 0.0,
              "last_drops_minimum_time": 3.0,
              "profile_can_override_stop_limits": false,
              "profile_can_override_tank_temperature": true,
              "stop_at_time": null,
              "stop_at_volume": null,
              "stop_at_weight": 51
          },
          "hot_water": {
              "disable_auto_tare": true,
              "stop_at_time": 0,
              "stop_at_volume": 0,
              "stop_at_weight": null,
              "temperature": 0
          },
          "hot_water_rinse": {
              "disable_auto_tare": true,
              "flow": 6.0,
              "stop_at_time": 20.0,
              "stop_at_volume": null,
              "stop_at_weight": null,
              "temperature": 92.0
          },
          "steam": {
              "disable_auto_tare": true,
              "stop_at_time": 90,
              "stop_at_volume": null,
              "stop_at_weight": null
          },
          "tank_water_threshold": {
              "temperature": 0
          }
      },
      "id": {
          "id": "D9:B2:48:AA:BB:CC",
          "name": "DE1"
      },
      "read_once": {
          "cpu_board_model": 1.3,
          "firmware_build_number": 1283,
          "firmware_model": "UNSET",
          "ghc_info": "GHC_ACTIVE|TOUCH_CONTROLLER_PRESENT|LED_CONTROLLER_PRESENT",
          "heater_voltage": 120,
          "hw_config_hexstr": "ffffffff",
          "model_hexstr": "ffffffff",
          "serial_number_hexstr": "00000000",
          "version_ble": {
              "api": 4,
              "blesha_hexstr": 1428072944,
              "changes": 60,
              "commits": 495,
              "release": 1.5
          },
          "version_lv": {
              "api": 0,
              "blesha_hexstr": 0,
              "changes": 0,
              "commits": 0,
              "release": 0.0
          }
      },
      "setting": {
          "auto_off_time": {
              "time": 30.0
          },
          "before_flow": {
              "heater_idle_temperature": 85.0,
              "heater_phase1_flow": 2.0,
              "heater_phase2_flow": 4.0,
              "heater_phase2_timeout": 5.0
          },
          "fan_threshold": {
              "temperature": 40
          },
          "start_fill_level": {
              "start_fill_level": 1.0
          },
          "steam": {
              "flow": 0.7,
              "high_flow_time": 2.0,
              "temperature": 160
          },
          "target_group_temp": {
              "temperature": 0.0
          },
          "time": {
              "timestamp": 0
          }
      },
      "state": {
          "state": {
              "state": "Sleep",
              "substate": "NoState"
          }
      }
  }
