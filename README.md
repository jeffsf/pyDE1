
# pyDE1

## License

Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under

GNU General Public License v3.0 only

SPDX-License-Identifier: GPL-3.0-only


## Overview

A fully functional, API-first implementation of core software for control
and use of the Decent Espresso DE1.

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


## Revision History

See also CHANGELOG.md

* 2021-10-31 – 0.9.0 Update for beta (functionally complete)
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
where the *beta* branch is now current.

The alpha branch will be retained there as some of the remaining development
tooling and examples will no longer be actively maintained. They will be
removed from the beta and future release branches.

## What's New

_**Please see CHANGELOG.md for more details**_

## 0.9.0 – 2021-10-31

### Overview

Version 0.9.0 represents the first beta release of this project. "Beta" here
represents a product that is believed to be functionally complete
for the intended scope and has undergone testing.


### New

* The flush-control features of *experimental* Firmware 1283 were implemented
  and include control of target duration, temperature, and flow. 46c0481

* Clean, Descale, and Transport functionality is now available through the API.
  65f2ac9

* Provide asynchronous firmware upload through API. d6a2dbc, 32436a9

* GET of DE1_STATE enabled. 2b4435e

* Rewrite of logging and logging configuration. "Early" logging is captured
  and routed to the log file, once it is opened. Log levels and formatters
  can be easily configured through the YAML config files. b759168, 39c714d,
  7df0397, d3e128c

* Provide logging over MQTT for client use (in addition to console and
  log file). 019bed0

* Profile frame logging provides "not" names for unset FrameFlags to clarify
  log messages. For example, the absence of `CtrlF` is now rendered as `CtrlP`.
  c842565

* MQTT "Will" implemented, reporting unexpected MQTT disconnects. 22d06b4

* Feature flags have been added to formalize access to DE1 and firmware
  abilities. d7405b0


### Fixed

* Loop-level, exception-initiated shutdowns now terminate more cleanly. 0b593d0

* An error condition when no scale was present during a "shot"
  has been resolved. ffae2f

* An error condition when a DE1 connected and the profile was not yet known
  has been resolved 58bbfad

* AutoTareNotification and StopAtNotification now populate sender. 9f39d08

* A very early termination of the program (before processes are defined) now
  terminates more cleanly. 4f95c34

* Reset the scale history if a gap in reports is too long, such as
  from a disconnect-reconnect sequence. 48a35ca

*See CHANGELOG.md for other changes and removals*

## Requirements

Python 3.8 or later.

Current plans are to continue to support two versions prior to
the latest Python version. [PEP 664](https://www.python.org/dev/peps/pep-0664/)
shows a schedule of October, 2022 for Python 3.11.0 release.
Users should plan on moving to at least Python 3.9 prior to that release.
Python 3.9 should be "standard" with the forthcoming, Raspberry Pi OS release
based on Debian Bullseye. Upstream Debian Bullseye is already available.

Available through `pip`:

* `bleak`
* `aiosqlite`
* `paho-mqtt`
* `PyYAML`
* `requests`

An MQTT broker compatible with MQTT 5 clients, such as `mosquitto 2.0`

A production-quality web server, such as `nginx` is highly recommended
operating as a reverse proxy, rather than directly exposing the Python
web server.

## Short-Term Priorities

* Stand-alone documentation
* Quick-start guide (awaiting release of Raspberry OS on Debian Bullseye)

## Out of Scope

* Single-command read of the DE1 debug register
* The private, "calibration" CUUID commands have not been "unlocked".


## Related Work (Other Projects)

* Componentize JavaScript real-time graph rendering
* Develop GraphQL access to database


## Status — Beta

This code is used on a daily basis for operation of the author's DE1.

This code is supplied under GPL v3.0 and is subject to the terms
of that license, including limitation of liability.
