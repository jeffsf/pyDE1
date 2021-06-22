# pyDE1

## License

Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under

GNU General Public License v3.0 only

SPDX-License-Identifier: GPL-3.0-only


## Overview

This represents work-in-progress to an API-first implementation of core software for a controller for the DE1.

The API is not stable at this time and is subject to change without notice.

This repo may have non-fast-forward commits.

Consumers can expect that there will be stable "inbound" (commands to the controller) and "outbound" (notification) APIs. At this time, the outbound payloads are JSON with a form similar to that being produced by the `.as_json()` method of the various subclasses of `EventPayload` and delivered over MQTT 5. 

Ideally, the consumers of these APIs will only need to understand high-level actions, such as "Here is a profile blob, please load it." The operations and choice of connectivity to the devices are planned on being "hidden" behind the APIs.

## Revision History

* 2021-06-22 - Updated for release 0.2.0
* 2021-06-11 – Updated for release 0.1.0
* 2021-06-08 – Initial release

## Status

This code is work in progress and is neither feature-complete nor fully tested. Although most features are working, as described in Section 15 and elsewhere of the GPLv3.0 `LICENSE`:

> THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY
APPLICABLE LAW.  EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT
HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY
OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM
IS WITH YOU.  SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF
ALL NECESSARY SERVICING, REPAIR OR CORRECTION. 

## What's New

### 0.2.0

#### Inbound Control and Query API

An inbound API has been provided using a REST-like interface over HTTP. The API should be reasonably complete in its payload and method definitions and comments are welcomed on its sufficency and completeness.

Both the inbound and outbound APIs run in separate *processes* to reduce the load on the controller itself.

GET should be available for the registered resources. See, in `src/pyDE1/dispatcher`

* `resource.py` for the registered resources, and
* `mapping.py` for the elements they contain, the expected value types, and how they nest.

`None` or `null` are often used to me "no value", such as for stop-at limits. As a result, though similar, this is not an [RFC7368 JSON Merge Patch](https://datatracker.ietf.org/doc/html/rfc7386).

In Python notation, `Optional[int]` means an `int` or `None`. Where `float` is specified, a JSON value such as `20` is permitted.

GET presently returns "unreadable" values to be able to better show the structure of the JSON. When a value is unreadable, `math.nan` is used internally, which is output as the JSON `NaN` token.

GET also returns empty nodes to illustrate the structure of the document. This can be controlled with the `PRUNE_EMPTY_NODES` variable in `implementation.py`

Although PATCH has been implemented for most payloads, PUT is not yet enabled. PUT will be the appropriate verb for`DE1_PROFILE` and `DE1_FIRMWARE` as, at this time, in-place modification of these is not supported. The API mechanism for starting a firmware upload as not been determined, as it should be able to abort as it runs in the background, as well as notify when complete. Profile upload is likely to be similar, though it occurs on a much faster time scale.

If you'd like the convenience of a GET of the same resource after a PATCH, you can set `READ_BACK_ON_PATCH` to `True` in `dispacher.py`

> The Python `http.server` module is used. It is not appropriate for exposed use.
> There is no security to the control and query API at this time.
> See further https://docs.python.org/3/library/http.server.html

It is likely that the server, itself, will be moved to a uWSGI (or similar) process. 

With either the present HTTP implementation or a future uWSGI one, use of a webserver, such as `nginx`, will be able to provide TLS, authentication, and authorization, as well as a more "production-ready" exposure.


#### Other Significant Changes

* `ShotSampleWithVolumeUpdates` (v1.1.0) adds `de1_time`. `de1_time` and `scale_time` are preferred over `arrival_time` as, in a future version, these will be estimates that remove some of the jitter relative to packet-arrival time.

* To be able to keep cached values of DE1 variables current, a read-back is requested on each write. 
* `NoneSet` and `NONE_SET` added to some `enum.IntFlag` to provide clearer representations
* Although `is_read_once` and `is_stable` have been roughed in, optimizations using them have not been done
* Disabled reads of `CUUID.ReadFromMMR` as it returns the request itself (which is not easily distinguashable from the data read. These two interpret their `Length` field differently, making it difficult to determine if `5` is an unexpected value or if it was just that 6 words were requested to be read.
* Scaling on `MMR0x80LowAddr.TANK_WATER_THRESHOLD` was corrected.


### 0.1.0

#### Outbound API

An outbound API (notifications) is provided in a separate process. The present implementation uses MQTT and provides timestamped, source-identified, semantically versioned JSON payloads for:

* DE1
	* Connectivity
	* State updates
 	* Shot samples with accumulated volume
 	* Water levels
* Scale
 	* Connectivity
 	* Weight and flow updates
* Flow sequencer
 	* "Gate" clear and set
	  	* Sequence start
	  	* Flow begin
	  	* Expect drops
	  	* Exit preinfuse
	  	* Flow end
	  	* Flow-state exit
	  	* Last drops
	  	* Sequence complete
  	* Stop-at-time/volume/weight
  		* Enable, disable (with target)
  		* Trigger (with target and value at trigger)

An example subscriber is provided in `examples/monitor_delay.py`. On a Raspberry Pi 3B, running Debian *Buster* and `mosquitto` 2.0 running on `::`, median delays are under 10 ms from *arrival_time* of the triggering event to delivery of the MQTT packet to the subscriber.

Packets are being sent with *retain* True, so that, for example, the subscriber has the last-known DE1 state without having to wait for a state change. Checking the payload's `arrival_time` is suggested to determine if the data is fresh enough. The *will* feature of MQTT has not yet been implemented.

A good introduction to MQTT and MQTT 5 can be found at HiveMQ:

* https://www.hivemq.com/mqtt-essentials/
* https://www.hivemq.com/blog/mqtt5-essentials-part1-introduction-to-mqtt-5/

One good thing about MQTT is that you can have as many subscribers as you want without slowing down the controller. For example, you can have a live view on your phone, live view on your desktop, log to file, log to database, all at once.

#### Scan For And Use First DE1 And Skale Found

Though "WET" and needing to be "DRY", the first-found DE1 and Skale will be used. The Scale class has already been designed to be able to have each subclass indicate if it recognizes the advertisement. Once DRY, the scanner should be able to return the proper scale from any of the alternatives. 

Refactoring of this is pending the formal release of `BleakScanner.find_device_by_filter(filterfunc)` from [bleak PR #565](https://github.com/hbldh/bleak/pull/565)


## Requirements

Python 3.8 or later.

Available through `pip`:
* `bleak`
* `aiologger`
* `asyncio-mqtt`

An MQTT broker compatible with MQTT 5 clients, such as `mosquitto 2.0` (see [below](#installing-mosquitto))

The Raspberry Pi version of Debian *Buster* ships with Python 3.7, which does not support named `asyncio.Task()` The "walrus operator" is also used.

Python 3.9 is expected to be part of Debian "next". Until that time, https://github.com/pyenv/pyenv can be used to install a version of your choice. On a RPi 3B, a complete build too under 15 minutes.

Development work is being done on *Buster* with Python 3.9.5 on a RPI 3B at this time.

The `bleak` library is supported on macOS, Linux, and Windows. Some development has also been done under macOS.

## What Seems To Be Working – High Level Functionality

* Connect by address to DE1
* Read and decode BLE characteristics 
* Encode and write BLE characteristics
* Read and decode MMR registers
* Encode and write MMR registers
* Upload firmware
* Parse JSON profile (v2) and upload
* Connect by address to SkaleII
* Scale processing for weight and flow, including period estimation
* Stop-at-time
* Stop-at-volume
* Stop-at-weight
* Enable/disable "shot" logging
* Outbound API over MQTT
* Basic connectivity tracking
* Find and use first DE1 and Skale
* Inbound control and query API over HTTP

The main process runs under Python's native `asyncio` framework. There are many tutorials out there that make asynchronous programming *look* easy. "Hello world!" is always easy. For a better understanding, I found Lynn Root's *[asyncio: We Did It Wrong](https://www.roguelynn.com/words/asyncio-we-did-it-wrong/)* to be very insightful.

## Work In Progress

* Convert `DE1`, `FlowSequencer` and probably `ScaleProcessor` to singletons. 
* Retain the possiblity of a "bare" scale (though the API does not yet support a second, independent scale).
* Provide graceful shutdown of all processes.
* Daemonize with supervision of Tasks and secondary processes.
* Bring in [find-first-matching functionality](https://github.com/hbldh/bleak/pull/565) when available from release `bleak`.
* Clean up the imports with likely a combination of pulling events and exceptions out, along with interface definitions.
* Documentation, including more doc strings, and typing

## Known Gaps

* Multiprocess logging needs to be unified
* Manage unexpected disconnects and reconnects
* Abort long-running actions, such as uploading a profile
* Timeouts on certain locks and await actions
* Adding, removing, or replacing the DE1 or scale with the `FlowSequencer`
* Potentially move to `aiologger` to reduce logging delays
* Single-command read of the DE1 debug register
* Clean, descale, transport
* Support for non-GHC machines

## Other Work

* Onboard, unattended sleep timeout with override (GUI or HA can provide complex "scheduler")
* Background firmware update
* MQTT will and MQTT 5 message expiry time

<a name="installing-mosquitto"></a>
## Installing Mosquitto 2.0

The example outbound API uses MQTT 5. If you don't already have a local MQTT 5 broker configured, there are some public test servers ("brokers"), such as https://test.mosquitto.org/, that can let you try things out quickly. A local broker is better from both from a security standpoint and for delay. The preferred configuration is to have a broker running on the same machine as this code on a loopback interface. Unfortunately, the [`paho` library does not support Unix domain sockets](https://github.com/eclipse/paho.mqtt.c/issues/864) at this time.

The example outbound API does not use encryption as it runs over a socket local to the host, the data is not considered "sensitive", and there is no control over the DE1. Token-based authentication, 
such as password, should be done over an encrypted channel if can be "snooped" by others.

Mosquitto 2.0 is a MQTT broker that supports MQTT 5. Older distributions only supply 1.x versions, such as 1.5.7 on 
Debian *Buster.* Debian *Bullseye* is showing that it will support 2.0.10 at this time. 

Mosquitto 2.0 can be installed onto Debian systems without needing to build from source using the 
[Mosquitto Debian Repository](https://mosquitto.org/blog/2013/01/mosquitto-debian-repository/). The usual caveats around making personal decisions about which sources you trust apply.

You likely will want both `mosquitto` (the broker) and `mosquitto-clients`.

Installing on RPi will enable the `mosquitto.service` using `/etc/mosquitto/mosquitto.conf`. 
If you've used v1.x in the past, I'd suggest reading [the release announcement](https://mosquitto.org/blog/2020/12/version-2-0-0-released/)
as well as the notes on [migrating from 1.x to 2.0](https://mosquitto.org/documentation/migrating-to-2-0/)


## Notes

The code is littered with TODOs and personal notes. Ray may find his name mentioned with some loose thoughts about changes. *These are loose thoughts worthy of some future discussion, not blockers and not direct requests!*