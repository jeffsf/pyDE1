..
    Copyright © 2021 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

pyDE1 Overview
==============

Description
-----------

A fully functional, API-first implementation of core software for
control and use of the Decent Espresso DE1.

It provides core components, which can be run as an unattended service
that automatically starts at boot, to supply stable, versioned APIs to
provide all primary functions of use of a DE1 and data collection around
it.

A web app has been able to demonstrate sufficiency of the APIs and
functionality for the majority of day-to-day operations, including
real-time graphing and history display. A running example is available,
linked from DecentForum.com. It uses the supplied, stand-alone "replay"
application to play back a shot in real time. This tool is also useful
for development of companion applications.

Profiles and real-time data are captured into a SQLite3 database that
allows multiple, concurrent access.

A stand-alone program is provided that can automatically upload "shots"
to Visualizer as soon as they complete. It can also notify consumers of
the URL returned.

An example program is provided that generates legacy-style, "shot files"
that are compatible with Visualizer and John Weiss' shot-plotting
programs.

The APIs are under semantic versioning. The REST-like, HTTP-transport
versions can be retrieved from ``version`` at the document root, and
also include the Python and package versions installed. Each of the
JSON-formatted, MQTT packets contains a ``version`` key:value for that
payload.

Consumers of these APIs should only need to understand high-level
actions, such as "Here is a profile blob, please load it." The
operations and choice of connectivity to the devices is "hidden" behind
the APIs.


Documentation and Source
------------------------

Documentation is available at https://pyde1.readthedocs.io/en/latest/

Source code is available at https://github.com/jeffsf/pyDE1.git


Requirements
------------

Python 3.8 or later.

Current plans are to continue to support two versions prior to the
latest Python version. `PEP
664 <https://www.python.org/dev/peps/pep-0664/>`__ shows a schedule of
October, 2022 for Python 3.11.0 release. Users should plan on moving to
at least Python 3.9 prior to that release. Python 3.9 is
"standard" with the Debian Bullseye distro, as well as the current,
Raspberry Pi OS release.

Available through ``pip`` and installed as dependencies:

-  ``aiosqlite``
-  ``bleak``
-  ``paho-mqtt``
-  ``PyYAML``
-  ``requests``

An MQTT broker compatible with MQTT 5 clients, such as ``mosquitto 2.0``

A production-quality web server, such as ``nginx`` is highly recommended
operating as a reverse proxy, rather than directly exposing the Python
web server.


Status — Release
----------------

This code is used on a daily basis for operation of the author's DE1.


License
-------

Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under

GNU General Public License v3.0 only

SPDX-License-Identifier: GPL-3.0-only
