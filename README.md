# pyDE1

## License

Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under

GNU General Public License v3.0 only

SPDX-License-Identifier: GPL-3.0-only

This code is work in progress. Although many features are working, as described in Section 15 and elsewhere of the GPLv3.0 `LICENSE`:

> THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY
APPLICABLE LAW.  EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT
HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY
OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM
IS WITH YOU.  SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF
ALL NECESSARY SERVICING, REPAIR OR CORRECTION. 

## Overview

This represents work-in-progress to an API-first implementation of core software for a controller for the DE1.

The API is not stable at this time and is subject to change without notice.

This repo may have non-fast-forward commits.

Consumers can expect that there will be stable "inbound" (commands to the controller) and "outbound" (notification) APIs. At this time, the outbound payloads are JSON with a form similar to that being produced by the `.as_json()` method of the various subclasses of `EventPayload` and delivered over MQTT 5. 

Ideally, the consumers of these APIs will only need to understand high-level actions, such as "Here is a profile blob, please load it." The operations and choice of connectivity to the devices are planned on being "hidden" behind the APIs.

## Revision History

2021-06-11 – Updated for release 0.1.0
2021-06-08 – Initial release

## What's New

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

The main process runs under Python's native `asyncio` framework. There are many tutorials out there that make asynchronous programming *look* easy. "Hello world!" is always easy. For a better understanding, I found Lynn Root's *[asyncio: We Did It Wrong](https://www.roguelynn.com/words/asyncio-we-did-it-wrong/)* to be very insightful.

## Work In Progress

* Develop an example "inbound" API implementation, probably REST-like with `nginx` over a pipe.
* Bring in [find-first-matching functionality](https://github.com/hbldh/bleak/pull/565) when available from release `bleak`
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
* * MQTT will and MQTT 5 message expiry time

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