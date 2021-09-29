# pyDE1

## License

Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under

GNU General Public License v3.0 only

SPDX-License-Identifier: GPL-3.0-only


## Overview

An API-first implementation of core software for control and use 
of the Decent Espresso DE1.

It provides core components, which can be run as an unattended service 
that automatically starts at boot, to supply stable, versioned APIs 
to provide all primary functions of use of a DE1 and data collection around it.

A web app has been able to demonstrate sufficiency of the APIs 
and functionality for the majority of day-to-day operations,
including real-time graphing and history display. A running example 
is available, linked from DecentForum.com. It uses the supplied,
stand-alone "replay" application to play back a shot in real time. 
This tool is also useful for development of companion applications.

Profiles and real-time data are captured into a SQLite3 database 
that allows multiple, concurrent access. 

A stand-alone program is provided that can automatically upload "shots"
to Visualizer as soon as they complete. It can also notify consumers 
of the URL returned.

An example program is provided that generates legacy-style, "shot files" that 
are compatible with Visualizer and John Weiss' shot-plotting programs.

The APIs are under semantic versioning. The REST-like, HTTP-transport
versions can be retrieved from `version` at the document root, and
also include the Python and package versions installed. Each of the
JSON-formatted, MQTT packets contains a `version` key:value for that
payload.

Consumers of these APIs should only need to understand high-level
actions, such as "Here is a profile blob, please load it." The
operations and choice of connectivity to the devices is "hidden"
behind the APIs.

Firmware upload is supported, though not yet revealed in the API.

## Revision History

See also CHANGELOG.md

* 2021-09-28 – 0.8.0 Implementation as unattended services
* 2021-08-12 – 0.7.0 sets profiles by ID, auto-reconnect, replay, uploader 
* 2021-07-25 – 0.6.0 adds database store
* 2021-07-14 – 0.5.0, "worked example" description
* 2021-07-03 – Updated for release 0.4.0, see also CHANGELOG.md
* 2021-06-26 – Content and organizational updates for release 0.3.0
* 2021-06-22 – Updated for release 0.2.0
* 2021-06-11 – Updated for release 0.1.0
* 2021-06-08 – Initial release

## Support and Discussion

Support and discussion is active at DecentForum.com, on Discord in the
Decent Espresso server and, to some extent, on the Espresso
Aficianados server in the Manufacturers: decent channel. Support is,
unfortunately, ***not*** available through Decent Diaspora on
Basecamp.

Thanks to all that have been trying this out and providing valuable feedback!

See also
[https://github.com/jeffsf/pyDE1](https://github.com/jeffsf/pyDE1)
where the *alpha* branch is current.

## What's New

_**Please see CHANGELOG.md for more details**_

## 0.8.0 – 2021-09-28

### Overview

This release focused on converting command-line executables to robust, 
self-starting, and supervised services. Both the core pyDE1 controller 
and the Visualizer uploader now can be started with `systemd` 
automatically at boot. Configuration of many parameters can be done 
through YAML files (simple, human-friendly syntax), by default in 
`/usr/local/pyde1/`. Command-line parameters, usable by the service unit files, 
can be used to override the config-file location.

Logging configuration may change prior to "beta". At this time it is only 
configurable in the output format and level for the *stderr* and *file* loggers.  
By default, the *stderr* logger is at the WARNING level abd without timestamps, 
as it is managed through `systemd` when being run as a service. A command-line 
parameter allows for timestamped output at the DEBUG level for interactive use.


### New

* Services run under `systemd`
    * Service ("unit") files for `pyde1.service` and `pyde1-visualizer.service`
    * Config files in YAML form
* Auto-off, configurable
* Track the IDs of connected Bluetooth devices for cleanup under Linux and 
    disconnect them at the Bluez level in the case of a non-graceful exit
* MQTT supports authorization and access-control lists
* Visualizer: Don't upload short "shots", such as for flushing (configurable)
* Stop-at-weight offset configurable through `pyde1.conf`
* Database:
    * Self-initialize, if needed
    * Check for the proper schema at start
* Replay: config file and command-line switches allow easier configuration, 
    including sequence ID and MQTT topic root


### Fixed

* MQTT (outbound) API will now detect connection or authentication failures 
    with the broker and terminate pyDE1
* FlowSequencer no longer raises exception when trying to report that 
    the steam time is not managed directly by the software. 
    (It is managed by the DE1 firmware.)
* Mass-flow estimates had an off-by-one error that was corrected
* Replay now properly reports sequence_id on gate notifications


### Changed

* Paths changed to `/var/log/pyde1` and `/var/lib/pyde1/pyde1.sqlite`
    by default (configurable)
* Refactored and unified shutdown processes
    * **NB: SIGHUP is no longer used for log rotation. 
            It is a termination signal.**
* Refactored supervised processes to handle uncaught exceptions and 
    properly terminate for automated restart
* Visualizer: log to `pyde1-visualizer.log` by default
* Stop-at-weight internally includes 170 ms to account for the "fall-time" 
    from the basket to the cup.
* Logging:
    * Switched to a file-watcher handler so that log rotation should 
        be transparent, without the need of a signal
    * Provide better control of formatting and level for use with `systemd` 
        (service) infrastructure
    * Change default file name to `pyde1.log`
    * Add `--console` command-line flag to provide timestamped, 
        DEBUG-level output to assist in development and debugging
    * Adjust some log levels so that INFO-level logs are more meaningful 
    * Removed last usages of `aiologger`
* The outbound API reports "disconnected" for the DE1 and scale when initialized


### Deprecated

* `find_first_and_load.py` (Use the APIs. It would have already been removed 
    if previously deprecated)


### Removed

* `ugly_bits.py` (previously deprecated)
* `try_de1.py` (previously deprecated)
* `DE1._recorder_active` and dependencies, including `shot_file.py` 
    (previously deprecated)
* Profile `from_json_file()` (previously deprecated)
* `replay_vis_test.py` -- Use `replay.py` with config or command-line options


## Requirements

Python 3.8 or later.

Available through `pip`:

* `bleak`
* `aiosqlite`
* `paho-mqtt`
* `requests`

An MQTT broker compatible with MQTT 5 clients, such as `mosquitto 2.0`
(see [below](#installing-mosquitto))

The Raspberry Pi version of Debian *Buster* ships with Python 3.7,
which does not support named `asyncio.Task()` The "walrus operator" is
also used.

Python 3.9 is expected to be part of Debian "next". Until that time,
https://github.com/pyenv/pyenv can be used to install a version of
your choice. On a RPi 3B, a complete build too under 15 minutes.

Development work is being done on *Bullseye* a RPi 4B (2 GB). 
The code is also being tested on *Buster* with Python 3.9.5 on a RPi 3B+.

The `bleak` library is supported on macOS, Linux, and Windows. Some
development has also been done under macOS.

## Short-Term Priorities

* Clean, descale, transport
* Abort long-running actions, such as uploading firmware
* Reveal firmware upload, clean, descale, and transport through API
* Stand-alone documentation
* Quick-start guide (awaiting release of Raspberry OS on Debian Bullseye)

## Known Gaps

* Timeouts on certain locks and await actions
* Single-command read of the DE1 debug register
* Clean up the imports
* More doc strings and typing

## Other Work

* Background firmware update
* MQTT will and MQTT 5 message expiry time
* MQTT notification of ERROR and higher log messages

## Related Work (Other Projects)

* Componentize JavaScript real-time graph rendering
* Develop GraphQL access to database


## Status — Late Alpha

This code is used on a daily basis for operation of tha author's DE1.

Although most features are working, as described in Section 15 and
elsewhere of the GPLv3.0 `LICENSE`:

> THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY
APPLICABLE LAW.  EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT
HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY
OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM
IS WITH YOU.  SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF
ALL NECESSARY SERVICING, REPAIR OR CORRECTION. 



## Some Older Notes of Explanatory Value

_**Please see CHANGELOG.md for newer details**_

### 0.2.0

#### Inbound Control and Query API

An inbound API has been provided using a REST-like interface over
HTTP. The API should be reasonably complete in its payload and method
definitions and comments are welcomed on its sufficiency and
completeness.

Both the inbound and outbound APIs run in separate *processes* to
reduce the load on the controller itself.

GET should be available for the registered resources. 
See, in `src/pyDE1/dispatcher`

* `resource.py` for the registered resources, and
* `mapping.py` for the elements they contain, the expected value types, 
  and how they nest.

`None` or `null` are often used to me "no value", such as for stop-at
limits. As a result, though similar, this is not an [RFC7368 JSON
Merge Patch](https://datatracker.ietf.org/doc/html/rfc7386).

In Python notation, `Optional[int]` means an `int` or `None`. Where
`float` is specified, a JSON value such as `20` is permitted.

GET presently returns "unreadable" values to be able to better show
the structure of the JSON. When a value is unreadable, `math.nan` is
used internally, which is output as the JSON `NaN` token.

GET also returns empty nodes to illustrate the structure of the
document. This can be controlled with the `PRUNE_EMPTY_NODES` variable
in `implementation.py`

Although PATCH has been implemented for most payloads, PUT is not yet
enabled. PUT will be the appropriate verb for`DE1_PROFILE` and
`DE1_FIRMWARE` as, at this time, in-place modification of these is not
supported. The API mechanism for starting a firmware upload as not
been determined, as it should be able to abort as it runs in the
background, as well as notify when complete. Profile upload is likely
to be similar, though it occurs on a much faster timescale.

> The Python `http.server` module is used. It is not appropriate for exposed use.
> 
> There is no security to the control and query API at this time.
> 
>  See further https://docs.python.org/3/library/http.server.html

It is likely that the server, itself, will be moved to a uWSGI (or similar) process.

With either the present HTTP implementation or a future uWSGI one, use
of a webserver, such as `nginx`, will be able to provide TLS,
authentication, and authorization, as well as a more
"production-ready" exposure.


#### Other Significant Changes

* `ShotSampleWithVolumeUpdates` (v1.1.0) adds `de1_time`. `de1_time`
  and `scale_time` are preferred over `arrival_time` as, in a future
  version, these will be estimates that remove some of the jitter
  relative to packet-arrival time.

* To be able to keep cached values of DE1 variables current, a
  read-back is requested on each write.

* `NoneSet` and `NONE_SET` added to some `enum.IntFlag` to provide
  clearer representations

* Although `is_read_once` and `is_stable` have been roughed in,
  optimizations using them have not been done

* Disabled reads of `CUUID.ReadFromMMR` as it returns the request
  itself (which is not easily distinguishable from the data
  read). These two interpret their `Length` field differently, making
  it difficult to determine if `5` is an unexpected value or if it was
  just that 6 words were requested to be read.

* Scaling on `MMR0x80LowAddr.TANK_WATER_THRESHOLD` was corrected.


### 0.1.0

#### Outbound API

An outbound API (notifications) is provided in a separate process. The
present implementation uses MQTT and provides timestamped,
source-identified, semantically versioned JSON payloads for:

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

An example subscriber is provided in `examples/monitor_delay.py`. On a
Raspberry Pi 3B, running Debian *Buster* and `mosquitto` 2.0 running
on `::`, median delays are under 10 ms from *arrival_time* of the
triggering event to delivery of the MQTT packet to the subscriber.

Packets are being sent with *retain* True, so that, for example, the
subscriber has the last-known DE1 state without having to wait for a
state change. Checking the payload's `arrival_time` is suggested to
determine if the data is fresh enough. The *will* feature of MQTT has
not yet been implemented.

A good introduction to MQTT and MQTT 5 can be found at HiveMQ:

* https://www.hivemq.com/mqtt-essentials/
* https://www.hivemq.com/blog/mqtt5-essentials-part1-introduction-to-mqtt-5/

One good thing about MQTT is that you can have as many subscribers as
you want without slowing down the controller. For example, you can
have a live view on your phone, live view on your desktop, log to
file, log to database, all at once.

#### Scan For And Use First DE1 And Skale Found

Though "WET" and needing to be "DRY", the first-found DE1 and Skale
will be used. The Scale class has already been designed to be able to
have each subclass indicate if it recognizes the advertisement. Once
DRY, the scanner should be able to return the proper scale from any of
the alternatives.

Refactoring of this is pending the formal release of
`BleakScanner.find_device_by_filter(filterfunc)` 
from [bleak PR#565](https://github.com/hbldh/bleak/pull/565)


## High Level Functionality

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
* Bleutooth scanning
* Find and use first DE1 and Skale
* Inbound control and query API over HTTP
* Save profiles and real-time data into SQLite3 with concurrent access
* Provide legacy-style, "shot file" data for Miha Rekar's
  [Visualizer](https://visualizer.coffee)
  and John Weiss' shot-plotting code 

The main process runs under Python's native `asyncio` framework. There
are many tutorials out there that make asynchronous programming *look*
easy. "Hello world!" is always easy. For a better understanding, 
I found Lynn Root's *[asyncio: We Did It
Wrong](https://www.roguelynn.com/words/asyncio-we-did-it-wrong/)* to
be very insightful.


<a name="installing-mosquitto"></a>
## Installing Mosquitto 2.0

The example outbound API uses MQTT 5. If you don't already have a
local MQTT 5 broker configured, there are some public test servers
("brokers"), such as https://test.mosquitto.org/, that can let you try
things out quickly. A local broker is better from both from a security
standpoint and for delay. The preferred configuration is to have a
broker running on the same machine as this code on a loopback
interface. Unfortunately, the [`paho` library does not support Unix
domain sockets](https://github.com/eclipse/paho.mqtt.c/issues/864) at
this time.

The example outbound API does not use encryption as it runs over a
socket local to the host, the data is not considered "sensitive", and
there is no control over the DE1. Token-based authentication, such as
password, should be done over an encrypted channel if it can be "snooped"
by others.

Mosquitto 2.0 is a MQTT broker that supports MQTT 5. Older
distributions only supply 1.x versions, such as 1.5.7 on Debian
*Buster.* Debian *Bullseye* is showing that it will support 2.0.10 at
this time.

Mosquitto 2.0 can be installed onto Debian systems without needing to
build from source using the [Mosquitto Debian
Repository](https://mosquitto.org/blog/2013/01/mosquitto-debian-repository/). The
usual caveats around making personal decisions about which sources you
trust apply.

You likely will want both `mosquitto` (the broker) and `mosquitto-clients`.

Installing on RPi will enable the `mosquitto.service` using
`/etc/mosquitto/mosquitto.conf`.  If you've used v1.x in the past, I'd
suggest reading [the release
announcement](https://mosquitto.org/blog/2020/12/version-2-0-0-released/)
as well as the notes on [migrating from 1.x to
2.0](https://mosquitto.org/documentation/migrating-to-2-0/)


## Notes

The code is littered with TODOs and personal notes. Ray may find his
name mentioned with some loose thoughts about changes. *These are
loose thoughts worthy of some future discussion, not blockers and not
direct requests!*
