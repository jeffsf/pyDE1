..
    Copyright © 2021-2023 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only


Bluetooth Scanning
==================

.. warning::

  The approach for scanning was significantly changed for v2.0.0

  This document is obsolete and will be removed on the next release

Overview
--------

Bluetooth scanning through the API was introduced in v0.5.0. This
document describes how applications can initiate a scan, obtain, and
interpret the results of those scans.

This document will be expanded to include discussion of selection and
changing of the DE1 and scale, when those APIs become available.

Revision History
~~~~~~~~~~~~~~~~

-  2023-01-21 - Marked as "obsolete" and will be deleted
-  2022-10-22 – Update for scanning changes deprecated in v1.2.0
-  2021-11-16 – Converted with ``pandoc`` to rST format
-  2021-07-06 – Initial revision

Bluetooth Scanning
------------------

General Notes on Bluetooth Scans
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A BLE scan is usually done passively, with the controller listening for
device advertisements. Depending on the device, these are usually sent
out several times a second when the device is a mode that it is
advertising. Battery-powered devices often restrict the duration during
which they are sending out advertisements. If the device is not sending
advertisements, it will not be detected.

If a device is already connected, it generally does not send out
advertisements. As a result, the connected DE1 and scale will not be
present in scans initiated after connection. As noted below, there may
be *cached* results, however directly obtaining the ID for the connected
DE1 and scale is recommended.

Initiating a Scan
~~~~~~~~~~~~~~~~~

A scan can be requested through the API with a PUT to ``Resource.SCAN``
such as

::

   curl -X PATCH --data '{"begin": null}' http://localhost:1234/scan

   [
       {
           "run_id": "BleakScannerWrapped_0x751b6b38_1",
           "timeout": 5
       }
   ]

Note that the scan is initiated asynchronously. The return to the caller
is “immediate”.

The ``begin`` parameter can take ``null`` to use the default timeout duration
or a positive value for the timeout in seconds. Use of ``true`` was deprecated
in v1.2.0 and removed in v1.5.0.

The two parameters returned provide the duration of the scan (seconds)
and a reference to “this scan” in updates that are provided over MQTT.

Following Scan Results
~~~~~~~~~~~~~~~~~~~~~~

When a scan is initiated, ``ScannerNotification`` packets are sent out
over MQTT. At the present time, these include both started/ended
notifications, as well as devices as they are detected.

The started and ended packets should always match in pairs on the
``run_id`` and, if API-initiated, with that in the response. Although
the ``run_id`` is presently somewhat readable at this time, it should be
considered as an opaque token.

.. note::

   The started packet is likely to arrive before the response from
   the HTTP API.

In addition to the standard notification fields, ``ScannerNotification``
packets include:

-  “action” — one of ``ScannerNotificationAction`` (started, found,
   ended)
-  “run_id” – opaque identifier (may be null)
-  “id” — (string or null) if a “found” notification, the unique ID of
   the device to the Bluetooth system
-  “name” – (string or null) if a “found” notification, the advertised
   name of the device (for example, “DE1” or “Skale”)

.. note::

   Although BlueZ uses the Bluetooth address as the ID,
   CoreBluetooth uses a UUID

::

   "run_id": "BleakScannerWrapped_0x751b6b38_1", "action": "started", "id": null, "name": null
   "run_id": "BleakScannerWrapped_0x751b6b38_1", "action": "found", "id": "CF:75:75:aa:bb:cc", "name": "Skale"
   [...]
   "run_id": "BleakScannerWrapped_0x751b6b38_1", "action": "ended", "id": null, "name": null

As noted above, connected devices will not appear in these messages.

Retrieving Currently Connected Devices
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For GUI display, it is often desired to have the presently connected
devices shown as well. These are usually not present in scans that have
been run after connection. They will often have expired from the
app-cached results as well.

At the present time, the system connects to at mote two devices, a DE1
and a scale. Their IDs can be retrieved through ``Resource.DE1_ID`` and
``Resource.SCALE_ID``

::

   $ curl http://localhost:1234/de1/id
   {
       "id": "D9:B2:48:aa:bb:cc",
       "name": "DE1"
   }

   $ curl http://localhost:1234/scale/id
   {
       "id": "CF:75:75:aa:bb:cc",
       "name": "Skale",
       "type": "AtomaxSkaleII"
   }

Retrieving Cached Results
~~~~~~~~~~~~~~~~~~~~~~~~~

In addition to reporting devices as they are discovered over MQTT, a
cache of discovered devices is retained internally. The cache has an
expiration time set by ``SCAN_CACHE_EXPIRY``. As a result, there may be
devices on the list that are no longer available, as well as potentially
no devices if it has been a while since a full scan has been done. A
list of devices can be obtained at ``Resource.SCAN_DEVICES``

::

   $ curl http://localhost:1234/scan/devices
   {
       "devices": [
           {
               "discovered": 1625607657.0419285,
               "id": "CF:75:75:aa:bb:cc",
               "name": "Skale"
           },
           {
               "discovered": 1625607656.25347,
               "id": "D9:B2:48:aa:bb:cc",
               "name": "DE1"
           }
       ]
   }

Filtering of Results
~~~~~~~~~~~~~~~~~~~~

Scan results are filtered to those that advertise a name that begins
with the one of the recognized prefixes. These include “DE1” as well as
all registered by each of the ``Scale`` subclasses defined in the code,
such as

::

   Scale.register_constructor(AtomaxSkaleII, 'Skale')
