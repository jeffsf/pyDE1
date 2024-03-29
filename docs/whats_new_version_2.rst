..
    Copyright © 2022-2023 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=======================
What's New in Version 2
=======================

--------
Overview
--------

pyDE1 Version 2 provides enhanced usability in several areas:

- Support of Acaia scales

- Support of Felicita Arc thanks to Mimoja

- Temporarily release control of a Bluetooth device

- Changing Bluetooth devices for a given role

- Synchronization across multiple clients

- Reworked Bluetooth scanning to simplify client logic

- Incorporation of Steam-To-Temperature functionality

- Script to convert profiles to JSON format, including from Visualizer

- Packaging and service definitions simplified

Although the DE1 and a Atomax Skale II mounted under the drip tray are
"dedicated" devices, many other scales and Bluetooth peripherals are not.
You might, for example, want to use your scale for pourover with a different
app. Your scale might need to be disconnected from Bluetooth to allow its
sleep timer to conserve battery. pyDE1 makes this easy by automatically
*releasing* devices when the DE1 sleeps, then automatically *capturing*
them when the DE1 wakes up. You can use your scale or thermometer
with other apps or just let them go to sleep without having to
explicitly disconnect them.

Another use case that has been requested is the ability to manage pyDE1
from multiple places. For example, you might have one UI on your phone
and another on a tablet in the kitchen. Although this was possible with
earlier versions, you'd have to refresh the display when you moved
to another device to catch up with changes in the controls.

.. note::

    The naming of some scripts and executables have been changed to simplify
    access to those scripts through packaging. You will need to update
    your service scripts to reflect the new install paths.

-------------------------
Managed Bluetooth Devices
-------------------------

pyDE1 Version 2 moves to a more sophisticated method for handling Bluetooth
devices. Rather than considering the low-level connectivity alone, it now
also considers if the device is "remembered". Rather than operating
on the Bluetooth layer, commands are now on the logical level, including:

- Assign address or UUID
- Capture
- Release
- "Forget" (by assigning null/None to the address/UUID)

.. note::

  The API endpoint has changed to ``de1/availability``.

  The ``de1/connectivity`` endpoint and ``ConnectivityChange`` notifications
  have been deprecated. They will be emulated through June, 2023
  for backward compatibility with existing clients.

Initialization of the device and its instance in code are handled
by pyDE1. pyDE1 will continue to function without a scale or
thermometer, although limited in some operations as the data
is not available.

"Ready" indicates that the device has been identified, initialized,
and should be able to accept further commands. There are typically
both API queries as well as broadcast messages around device availability,
including the "role" of the device (DE1, scale, thermometer, other, ...)
in controlling the system.

Multiple requests can be "stacked up", such a capture followed by release.
This queue is only two deep, tracking the current action in progress
as well as the desired end state, if different that that in progress.
Requests that arrive with an operation in progress just change the
desired end state without lengthening the queue. If the desired end state
is different that that in progress, the in-flight operation will be cancelled,
if possible. This allows, for example, releasing a device that isn't online,
but has a pending capture request.

- Initial — The device exists, but no further actions have been taken.
  In the initial state the device typically does not have an
  assigned address/UUID (hereafter "address"). Assigning an address
  will typically make a release request. It may be a generic device.
  See further :ref:`class-changing-mbd`.

- Capturing — In the process of connecting to a known device, which may
  or may not be online and visible to the controller

- Captured – The device has been located and is connected at the
  Bluetooth level. There are no pending changes requested.

  - A *captured* device, once initialized and ready for commands,
    is marked as *ready.*

  - A device that is not *captured* is never *ready.*

- Releasing – The device is in the process of moving to a the released
  state.

- Released — The device is no longer in transition between states.
  If it has an address, a capture request can be made.

Changing the device's address will result in it being released,
even if captured or ready. In the case of scales (and likely for
thermometers, when implemented), the device is "generified". This
is because the appropriate device class is not determined until
Bluetooth advertisement packets are seen. It is a backlog item
to consider if maintaining a registry of known address-to-class
mappings is worthwhile.

.. _class-changing-mbd:

Class-Changing Managed Bluetooth Devices
========================================

As soon as the device filling a given role can change, things get complicated.
Either all internal connections to the device's implementation need to be
torn down and reinitialized, or somehow the implementation needs to adapt
to the new device. Complete tear-down and reinitialization is unattractive
as it requires logic in all other components. Python does not officially support
objects that change class. Several approaches to maintaining a consistent set
of references as the class changed were explored. Although not supported,
changing the class of an instance was selected. There is a set of
automated tests to confirm that the expected behavior is present as newer
versions of Python are released.

Generic Managed Bluetooth Device
--------------------------------

The generic device, such as ``GenericScale`` is one that
embodies most of the behavior all of the specific devices.
It is not so much "least common denominator" but more of
a "guaranteed stable plug-in point" for a device in the role,
as that device comes and goes, or even changes type.
If a consumer has a reference to "the scale", then that reference
is good even if there is no physical device connected. If a consumer
subscribed to an event, it remains subscribed even as the physical
device comes and goes, or changes type.

The generic device provides a "device-changed" event to allow consumers
that are taking advantage of device-specific features that the device
may no longer supply those features or otherwise behave differently.

Often a generic device will be instantiated for a role without an address.
Assigning an address to the device will involve releasing the device.
It is valid to request capture of a generic device. When advertisement
packets are received, code will transition the generic device to an appropriate
specific device, if there is a match. Consumers interested in details
of the device class can wait on the device-changed event. Those that
utilize only the common functionality should only need to follow the ready
status.

For the curious, the operation of generic => specific => generic transitions
can be seen in

- ``_initialize_after_connection()``
- ``_adopt_class()``
- ``_leave_class()``


--------------------------------------
Enhancements in Client Synchronization
--------------------------------------

There is nothing preventing multiple clients from accessing the pyDE1 APIs.
It works quite well to, for example, turn on the DE1 from one device
and control it from another. However, in previous versions,
changes made on one device weren't automatically reflected on the other.

When changes are made to the pyDE1 controller or a DE1 connects,
the resulting state of the impacted area this information
is now sent over MQTT to its subscribers.

At this time the areas include the following topics:

- ``update/de1/control``
- ``update/de1/setting``
- ``update/de1/calibration``
- ``update/de1/profile/id``

Timestamps are available in the MQTT packets as well as in the HTTP response
header ``x-pyde1-timestamp`` to assist in disambiguation of the two sources.

Additionally, availability and DE1 state have been added to the HTTP responses
in a format compatible with clients retaining state as "mqtt".


----------------------------
Rework of Bluetooth Scanning
----------------------------

The approach to Bluetooth scanning was reworked to use changes in the Bleak
Bluetooth library as well as to simplify client code.

Scanning is now by "role", one of

- DE1
- Scale
- Thermometer

The scan results are reported over MQTT and consist of a boolean ``scanning``
indicating if a scan is still underway, and ``devices``, an array of
accumulated information about all devices matching the requested role
seen during the scan. The packet contains

- ``address``
- ``name``
- ``rssi``

for each device, with updates as additional devices are found during the scan.

The results are no longer retained in the ``DiscoveredDevices`` structure and the APIs
to access that structure are not available.

.. note::

    MAPPING 7.0.0 — RESOURCE 5.0.0


- ``Resource.SCAN`` (``scan``)
  - Now takes a string representing the role
  - Can no longer be PATCH-ed (use PUT with the desired DeviceRole)

- ``Resource.SCAN_DEVICES`` (``scan_devices``) -- has been removed

.. code-block::

    class DeviceRole (enum.Enum):
        DE1 = 'de1'
        SCALE = 'scale'
        THERMOMETER = 'thermometer'
        OTHER = 'other'
        UNKNOWN = 'unknown'


--------------------
Steam-To-Temperature
--------------------

Previously developed as a separate app, now integral with pyDE1

https://github.com/jeffsf/steam-to-temperature

Use
===

- Set the BlueDOT to either °C or °F, as desired.

- The program will attempt to connect to the BlueDOT when the DE1 is
  not sleeping. If not immediately found, it will retry, falling back
  to once every 30 seconds. The BlueDOT will beep briefly to indicate
  connection. If you're looking at the display, you'll see the high
  alarm displaying freezing (0°C or 32°F) while beeping.

- If the DE1 sleeps, it will disconnect from the BlueDOT, allowing it
  to be used elsewhere with the Thermoworks app. As long as it is
  disconnected from the Thermoworks app and is on and in range, it
  will reconnect when the DE1 wakes.

- Set the desired target temperature as the high alarm on the BlueDOT

- Put the probe in the steaming pitcher.

- Start steaming with the GHC (or app control for non-GHC machines)

- The steam will pause automatically, going into "puff mode". Remove
  the pitcher. (For tiny volumes, the puffs can be sufficient to raise
  the temperature slightly above target.)

- Stop the steaming with the GHC or app control. This will trigger
  the usual auto-purge sequence.


-------------------------------------------------
Utility to Convert Legacy Profiles to JSON format
-------------------------------------------------

``de1-profile-as-json`` is now packaged and installed in the PATH
of the venv used to install pyDE1, such as
``/home/pyde1/venv/pyde1/bin/de1-profile-as-json``. If the venv is active
for the user's shell, it will be directly available without specifying
the full path. It can also be run using the full path without activating
the venv.

This utility will accept a legacy profile, including downloading one from
Visualizer, and output a JSON version.

    As most of the profiles distributed fail to properly attribute the author,
    the author can be overridden on the command line with the
    ``-a`` or ``--author`` flag.

    Without any arguments, the utility accepts input from STDIN and writes
    to STDOUT.

    The input can be specified from a file using the ``-i`` or ``--input`` flag
    followed by the filename.

    Alternately, a Visualizer URL for a profile or a Visualizer "share code"
    (four characters) can be entered after the ``-v`` or ``--visualizer`` flag.

    The output filename can optionally be specified using the
    ``-o`` or ``--output`` flag.

    If one specifies the ``-d`` or ``--directory`` flag followed by a directory,
    the output will be placed in that directory.

    If ``-d`` is specified, but not ``-o`` for a specific output name,
    a reasonable guess will be made based on the input file name
    and profile title.

    If the output file already exists, ``-f`` or ``--force``
    can be used to overwrite.

::

    usage: de1-profile-as-json [-h] [-a AUTHOR] [-i INPUT | -v REF] [-o OUTPUT] [-d DIR] [-f]

    Executable to open a Tcl profile file and write as JSON v2.1. Input and output default to STDIN and STDOUT

    optional arguments:
      -h, --help                  show this help message and exit
      -a AUTHOR, --author AUTHOR  Replace author
      -i INPUT, --input INPUT     Input file
      -v REF, --visualizer REF    Visualizer short code or profile URL
      -o OUTPUT, --output OUTPUT  Output file
      -d DIR, --dir DIR           Output directory
      -f, --force                 Overwrite if output exists


Although it is believed that the conversion is done accurately, it is always
worthwhile to check the results prior to use.


-------------------------------
Profile Specification JSON v2.1
-------------------------------

This release includes a description of the JSON profile format,
extended from Mimoja's original work. This document is structured
as TypeScript for simplicity as well as potential reuse. However,
it has not been validated in the context of a TypeScript app.

See :doc:`profile_json`


--------------------------------------
Packaging / Service Definition Changes
--------------------------------------

The primary executables and scripts are now packaged in the ``bin/`` directory
of the venv into which pyDE1 is installed. They are self-sufficient in that
the venv does not need to be "activated" to run them in the context of that
venv. This simplifies service scripts, as well as making utilities such as
``pyde1-disconnect-btid.sh`` easily available. These scripts include:

- ``pyde1-run`` -- the main executable of the pyDE1 controller
- ``pyde1-run-visualizer`` -- a companion executable that uploads shots
  to the Visualizer service
- ``pyde1-disconnect-btid.sh`` -- a shell script to disconnect any Bluetooth
  devices that were recorded as being connected by pyDE1 in the event of
  a very ungraceful exit or during development
- ``pyde1-replay`` -- a utility script to replay the packets from a previous
  shot over MQTT

New versions of the ``.service`` files are packaged. The new versions no longer
require determining the "deep" path of the file (shown here as of v2.0)::

  [Unit]
  Description=Main controller processes for pyDE1
  Wants=mosquitto.service
  After=syslog.target mosquitto.service

  [Service]
  # This needs to be the same user that "owns" the database
  User=pyde1
  Group=pyde1

  ExecStartPre=/home/pyde1/venv/pyde1/bin/pyde1-disconnect-btid.sh
  # The executable name can't be a variable
  ExecStart=/home/pyde1/venv/pyde1/bin/pyde1-run
  ExecStopPost=/home/pyde1/venv/pyde1/bin/pyde1-disconnect-btid.sh

  Restart=always
  StandardError=journal
  # Sets the process name to that of the service
  SyslogIdentifier=%N

  [Install]
  WantedBy=multi-user.target
