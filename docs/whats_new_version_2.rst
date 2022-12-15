..
    Copyright © 2022 Jeff Kletsky. All Rights Reserved.

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

Although the DE1 and a Atomax Skale II mounted under the drip tray are
"dedicated" devices, many other scales and Bluetooth peripherals are not.
You might, for example, want to use your scale for pourover with a different
app. Your scale might need to be disconnected from Bluetooth to allow its
sleep timer to conserver battery. pyDE1 makes this easy by automatically
*releasing* devices when the DE1 sleeps, then automatically *capturing*
them when the DE1 wakes up. You can use your scale or thermometer
with other apps or just let them go to sleep without having to
explicitly disconnect them.

Another use case that has been requested is the ability to manage pyDE1
from multiple places. For example, you might have one UI on your phone
and another on a tablet in the kitchen. Although this was possible with
earlier versions, you'd have to refresh the display when you moved
to another device to catch up with changes in the controls.

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


Enhancements in Client Synchronization
======================================

With previous versions, there was nothing preventing multiple clients
from accessing the pyDE1 APIs. It worked quite well to, for example,
turn on the DE1 from one device and control it from another. However,
changes made on one device weren't automatically reflected on the other.

When changes are made to the pyDE1 controller or a DE1 connects,
the resulting state of the impacted area this information
is now sent over MQTT to its subscribers.

At this time the areas include the following topics:

- ``update/version``
- ``update/de1/read_once_values``
- ``update/de1/feature_flags``
- ``update/de1/control``
- ``update/de1/setting``
- ``update/de1/calibration``
- ``update/de1/profile/id``

Timestamps are available in the MQTT packets as well as in the HTTP response
header ``x-pyde1-timestamp`` to assist in disambiguation of the two sources.


Rework of Bluetooth Scanning
============================

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
- ``RSSI``
for each device, with updates as additional devices are found during the scan.

The results are no longer retained in the ``DiscoveredDevices`` structure and the APIs
to access that structure are not available.

.. note::

    MAPPING 7.0.0, RESOURCE 5.0.0


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


Steam-To-Temperature
====================

Previously developed as a separate app, now integral with pyDE1

https://github.com/jeffsf/steam-to-temperature

Use
---

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