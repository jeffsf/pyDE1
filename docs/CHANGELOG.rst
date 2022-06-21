..
    Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

=========
Changelog
=========

------------------
1.2.0 - 2022-06-20
------------------

Overview
========

Changed
=======

* DE1XXL is properly recognized from MMR0x80LowAddr.V13_MODEL -- ''eca93bb''

* The API_Substates added by FW v1315/1316 were added -- ''2d38e42''

--------------------
1.2.0b1 - 2022-03-19
--------------------

Overview
========

RESOURCE and MAPPING changes to enable uploading profiles
without requiring DE1 connectivity. Use case suggested by EBengoechea, thanks!

Scale-management reworked in preparation of further changes to support
Acaia and other scales that are typically not connected 24x7.

Ending a sequence before flow starts should no longer bloat the database.

Changed
=======

scale: Change logger name to Scale.AtomaxSkaleII - ``fd48ec3``

File logging can be disabled and SubscribedEvent can notify
without a pipe present (for testing) - ``6b5e6cf``, ``d78cfa0``

Add config.de1.SEQUENCE_WATCHDOG_TIMEOUT (default, 270 seconds)- ``a4a2dda``

Fixed
=====

de1: scale: Quiet all connection attempt/fail logging when "not logging"
- ``6936f24``

scale: Factory now properly checks keys of name-to-class mapping - ``323bbca``

Python 3.10: Change import for Callable from collections to typing - ``39f7a57``

Sequences that are terminated before flow starts should no longer continue
writing to the database. Watchdog timer also added - ``a4a2dda``

Deprecated
==========

"first_if_found", "id", "scan" deprecated - ``207a492``

To start a scan, the parameter has been changed to prefer a positive number
for the timeout, or null (to accept the default). Use of a bool here
has been DEPRECATED. The preferred forms include:

.. code-block::

  {'begin': null}
  {'begin': 5}
  {'begin': 5.0}

To start a scan and select the first-found device of the desired type,
set the id to 'scan'. Use of the 'first_if_found' key has been DEPRECATED:
The preferred forms include:

.. code-block::

  {'id': 'scan'}
  {'id': 'aa:bb:cc:dd:ee:ff'}
  {'id': null}


DEPRECATED forms include:

.. code-block::

  {'begin': true}
  {'begin': false}
  {'first_if_found': true}
  {'first_if_found': false}


------------------
1.1.0 – 2022-01-24
------------------

Fixed: Long profiles should no longer time out when selecting by ID -
``f1f383a``

Other functional changes described at :ref:`changelog_v1.1.0b1`

* Trivial documentation changes from 1.1.0b2
* Updated documentation from 1.1.0b1

--------------------
1.1.0b2 – 2022-01-22
--------------------

Overview
========

Updated, expanded, and reorganized installation documentation

Changed
=======

Documentation (only)

.. _changelog_v1.1.0b1:

--------------------
1.1.0b1 – 2022-01-14
--------------------

Overview
========

Resolves shutdown issue with MQTT unconnected, DE1 config-file values,
improves some logging, updates FeatureFlag for FW 1293,
improves compatability with Manjaro (OS),
fixes documentation-generation issue.

Changed
=======

* Reduce log severity for unimplemented MMRs 0x3820 and 0x3824 – ``0125b72``
* ``FeatureFlag`` includes ``sched_idle`` flag, active for FW 1293 and later –
  ``64ee7f7``
* Timeouts on CUUID request/notify log changed wording to state
  that it could also be the write or the lack of a notify received that
  caused the timeout – ``a675f50``
* Removed stray comment from ``20-create-dirs.sh`` – ``6070984``
* Link ``README.rst`` for documentation generation – ``bb640f3``

Fixed
=====

* Shutdown without an MQTT connection does not try (and fail) to close it –
  ``adda65e``
* DE1 is initialized with config-file values, rather than default –
  ``f7d6393``
* HTTP API now returns a more descriptive error if the payload data type is
  incorrect – ``43614df``
* `disconnect-btid.sh` should no longer cause `sh` errors with Manjaro OS –
  ``d3a3c65``
* Service definitions updated to use ``StandardError=journal`` – ``ac0ead7``


------------------
1.0.0 — 2021-12-11
------------------

Overview
========

First release version.

Changed
=======

* Allow request of Idle from a refill state
  (apparently not acted on by the DE1) - ``55d81bb``
* Allow "force" of DE1 Idle from any state, enabled through config -
  ``05adc93``
* Prereqs updated to current versions  - ``5d320cb``

RESOURCE 3.6.0
------------------

* Add ``NO_REQUEST`` mode to trigger a report from the DE1 - ``a52cd6f``
* Add ``END_STEAM`` mode to support steam-to-temperature - ``24d7b52``


Fixed
=====

* Double-counting of scale delay was removed, improving scale-to-DE1 time
  alignment - ``886016a``


-------------------
0.10.0 – 2021-11-21
-------------------

Overview
========

Documentation, including installation, added. Installation scripts,
tested with Raspberry Pi OS Lite (Release date: October 30th 2021,
Kernel version: 5.10) available in the source repo.

New
===

* Documentation viewable at https://pyde1.readthedocs.io/en/latest/
* Install scripts in the source repo in the ``install`` directory
* Provide config for TLS for MQTT clients - ``427b3e0``

Changed
=======

* Documentation reorganized and consolidated into the ``docs`` directory
* ``disconnect-btid.sh`` is now expected at
  ``/usr/local/bin/pyde1-disconnect-btid.sh`` by ``pyde1.service``

MAPPING 4.0.1
-----------------

* MODULES_FOR_VERSIONS consistent with requirements - ``40c4ce0``

Fixed
=====

* utils: data_as_readable() now handles "undecodable" byte sequences - ``08aef05``
* packaging: Include schema and service files - ``4caf736``


------------------
0.9.0 – 2021-10-31
------------------

Overview
========

Functionality for the beta release completed and tested.

New
===

-  The flush-control features of *experimental* Firmware 1283 were
   implemented and include control of target duration, temperature, and
   flow. - ``46c0481``

-  Clean, Descale, and Transport functionality is now available through
   the API. - ``65f2ac9``

-  Provide asynchronous firmware upload through API. - ``d6a2dbc``, ``32436a9``

-  GET of DE1\_STATE enabled. - ``2b4435e``

-  Rewrite of logging and logging configuration. "Early" logging is
   captured and routed to the log file, once it is opened. Log levels
   and formatters can be easily configured through the YAML config
   files. - ``b759168``, ``39c714d``, ``7df0397``, ``d3e128c``, ``cabab97``

-  Provide logging over MQTT for client use (in addition to console and
   log file). - ``019bed0``

-  Profile frame logging provides "not" names for unset FrameFlags to
   clarify log messages. For example, the absence of ``CtrlF`` is now
   rendered as ``CtrlP``. - ``c842565``

-  MQTT "Will" implemented, reporting unexpected MQTT disconnects.
   - ``22d06b4``

-  Feature flags have been added to formalize access to DE1 and firmware
   abilities. - ``d7405b0``

Changed
=======

-  ``c_api`` was updated with new information. - ``46c0481``

-  The firmware version is read early in the DE1 initialization to
   determine the range of valid MMRs and how to efficiently read them.
   - ``46c0481``

-  The ``ModeControl`` class was refactored into ``flow_sequencer``.
   - ``46c0481``

-  MMRs that are not able to be decoded (such as not implemented), are
   logged along with the value received. - ``2d0fa24``

-  Return 400 Bad Request for PATCH/PUT with no content. - ``d00bd24``

-  Change MQTT to not request retaining messages from pyDE1. - ``8a8ba5e``

-  Logging level and wording changes. - ``99ec22f``, ``b31c850``

-  Rework imports to remove order dependencies and simplify. - ``c895f7d``,
   - ``b31c850``

-  Improve reconnection algorithm for DE1 and Scale. - ``6be3e5a``

-  Improve camelcase\_from\_underscore(). - ``0b40fe9``

-  Do not try to reconnect DE1 or Scale while shutting down. - ``bd21a93``

-  Inbound (HTTP) API: Check DE1 and scale is\_ready instead of
   is\_connected. - ``5de28e7``

MAPPING 4.0.0
-----------------

* Rewrites ``IsAt`` to use an enum, rather than the class to define
  the target, simplifying package inclusion. - ``78cea85``

Fixed
=====

-  Loop-level, exception-initiated shutdowns now terminate more cleanly.
   - ``0b593d0``

-  An error condition when no scale was present during a "shot" has been
   resolved. ffae2f

-  An error condition when a DE1 connected and the profile was not yet
   known has been resolved - ``58bbfad``

-  AutoTareNotification and StopAtNotification now populate sender.
   - ``9f39d08``

-  A very early termination of the program (before processes are
   defined) now terminates more cleanly. - ``4f95c34``

-  ScaleProcessor: Reset the history if a gap in reports is too long,
   such as from a disconnect-reconnect sequence. - ``48a35ca``


Removed
=======

-  Remove unused Config.set\_logging(). - ``2b104e6``

-  Remove feature.py as previously incorporated into FeatureFlag.
   - ``469ee96``

------------------
0.8.0 – 2021-09-28
------------------

Overview
========
This release focused on converting command-line executables to robust,
self-starting, and supervised services. Both the core pyDE1 controller
and the Visualizer uploader now can be started with ``systemd``
automatically at boot. Configuration of many parameters can be done
through YAML files (simple, human-friendly syntax), by default in
``/usr/local/pyde1/``. Command-line parameters, usable by the service
unit files, can be used to override the config-file location.

Logging configuration may change prior to "beta". At this time it is
only configurable in the output format and level for the *stderr* and
*file* loggers.

By default, the *stderr* logger is at the WARNING level abd without
timestamps, as it is managed through ``systemd`` when being run as a
service. A command-line parameter allows for timestamped output at the
DEBUG level for interactive use.

New
===

-  Services run under ``systemd``

   -  Service ("unit") files for ``pyde1.service`` and
      ``pyde1-visualizer.service``
   -  Config files in YAML form

-  Auto-off, configurable
-  Track the IDs of connected Bluetooth devices for cleanup under Linux
   and disconnect them at the Bluez level in the case of a non-graceful
   exit
-  MQTT supports authorization and access-control lists
-  Visualizer: Don't upload short "shots", such as for flushing
   (configurable)
-  Stop-at-weight offset configurable through ``pyde1.conf``
-  Database:

   -  Self-initialize, if needed
   -  Check for the proper schema at start

-  Replay: config file and command-line switches allow easier
   configuration, including sequence ID and MQTT topic root

Changed
=======

.. warning::
   SIGHUP is no longer used for log rotation. It is a
   termination signal.

-  Paths changed to ``/var/log/pyde1`` and
   ``/var/lib/pyde1/pyde1.sqlite`` by default (configurable)
-  Refactored and unified shutdown processes
-  Refactored supervised processes to handle uncaught exceptions and
   properly terminate for automated restart
-  Visualizer: log to ``pyde1-visualizer.log`` by default
-  Stop-at-weight internally includes 170 ms to account for the
   "fall-time" from the basket to the cup.
-  Logging:

   -  Switched to a file-watcher handler so that log rotation should be
      transparent, without the need of a signal
   -  Provide better control of formatting and level for use with
      ``systemd`` (service) infrastructure
   -  Change default file name to ``pyde1.log``
   -  Add ``--console`` command-line flag to provide timestamped,
      DEBUG-level output to assist in development and debugging
   -  Adjust some log levels so that INFO-level logs are more meaningful
   -  Removed last usages of ``aiologger``

-  The outbound API reports "disconnected" for the DE1 and scale when
   initialized

Fixed
=====

-  MQTT (outbound) API will now detect connection or authentication
   failures with the broker and terminate pyDE1
-  FlowSequencer no longer raises exception when trying to report that
   the steam time is not managed directly by the software. (It is
   managed by the DE1 firmware.)
-  Mass-flow estimates had an off-by-one error that was corrected
-  Replay now properly reports sequence\_id on gate notifications

Deprecated
==========

-  ``find_first_and_load.py`` (Use the APIs. It would have already been
   removed if previously deprecated)

Removed
=======

-  ``ugly_bits.py`` (previously deprecated)
-  ``try_de1.py`` (previously deprecated)
-  ``DE1._recorder_active`` and dependencies, including ``shot_file.py``
   (previously deprecated)
-  Profile ``from_json_file()`` (previously deprecated)
-  ``replay_vis_test.py`` -- Use ``replay.py`` with config or
   command-line options


------------------
0.7.0 – 2021-08-12
------------------

Schema Upgrade Required
=======================

.. warning::
   Backup your database before updating the schema.

See SQLite ``.backup`` for details if you are not familiar.

This adds columns for the ``id`` and ``name`` fields that are now being
sent with ``ConnectivityUpdate``

New
===

-  Stand-alone app automatically uploads to Visualizer on shot
   completion
-  PUT and GET of DE1\_PROFILE\_ID allows setting of profile by ID
-  A stand-alone "replay" utility can be used to exercise clients, such
   as web apps
-  Both the DE1 and scale will try to reconnect on unexpected disconnect
-  Add ``DE1IncompleteSequenceRecordError`` for when write is not yet
   complete
-  Variants of the EB6 profile at different temperatures

Changed
=======

-  Better logging when waiting for a sequence to complete times out
-  Capture pre-sequence history at all times so "sync" is possible on
   replay
-  Removed read-back of CUUID.RequestedState as StateInfo provides
   current state
-  Removed "extra" last-drops check
-  Allow more API requests when DE1 or scale is not ready
-  Use "ready" and not just "connected" to determine if the DE1 or scale
   can be queried
-  Allow [dis]connect while [dis]connected
-  ``ConnectivityChange`` notification includes ``id`` and ``name`` to
   remove the need to call the API for them
-  Improve error message on JSON decode by including a snippet around
   the error
-  Set the default first-drops threshold to 0.0 for fast-flowing shots

RESOURCE 3.0.0
------------------

-  Changes previously unimplemented UPLOAD_TO_ID

   ::

       DE1_PROFILE_ID
       DE1_FIRMWARE_ID

Database Schema 2
-----------------

See ``upgrade.001.002.sql``

::

    PRAGMA user_version = 2;

    BEGIN TRANSACTION;

    ALTER TABLE connectivity_change ADD COLUMN id TEXT;
    ALTER TABLE connectivity_change ADD COLUMN name TEXT;

    END TRANSACTION;

Fixed
=====

-  Legacy "shot" files handle zero flow in "resistance" calculation
-  Properly end recording of a sequence if it is interrupted
-  FlowSequencer last-drops gate set during sequence
-  Correct logic error in stopping recorder at end of sequence
-  Correct reporting of not-connected conditions to HTTP API
-  Correct scale-presence checking for PUT and PATCH requests
-  Handle missing Content-Length header
-  Incorrect error message around API request for Sleep removed
-  ``pyDE1.scanner`` should now import properly into other code
-  Steam-temperature setter now can set 140-160 deg. C
-  Type errors in validation of API inputs properly report the expected
   type



------------------
0.6.0 – 2021-07-25
------------------

**The Mimoja Release**

    I am not sure how / where to store shots and profiles. I hate it to
    only have it browser local.

*So do I. Wonder no longer.*

New
===

A SQLite3 database now saves all profiles uploaded to the DE1, as well
as capturing virtually all real-time data during all flow sequences,
including a brief set of data from *before* the state transition.

Profiles are unique by the content of their "raw source" and also have a
"fingerprint" that is common across all profiles that produce the same
"program" for the DE1. Changing a profile's name alone does not change
this fingerprint. Changing the frames in a profile without changing the
name changes both the ID of the profile, as well as its fingerprint.
These are both calculated using SHA1 from the underlying data, so should
be consistent across installs for the same source data or frame set.

Profiles can also be searched by the customary metadata:

-  Title
-  Author
-  Notes
-  Beverage type
-  Date added

``aiosqlite`` and its dependencies are now required.

Legacy-style shot data can be extracted from the database by an
application other than that which is running the DE1. Creating a
Visualizer-compatible "file" for upload can be done in around 80-100 ms
on a RPi 3B. If written to a physical file, it is also compatible with
John Weiss' shot-plotting programs. See ``pyDE1/shot_file/legacy.py``

The database retains the last-known profile uploaded to the DE1. If a
flow sequence beings prior to uploading a profile, it is used as the
"most likely" profile and identified in the database with the
``profile_assumed`` flag.

.. note::
   The database needs to be manually initialized prior to use.

One approach is

::

    sudo -u <user> sqlite3 /var/lib/pyDE1/pyDE1.sqlite3 \
    < path/to/pyDE1/src/pyDE1/database/schema/schema.001.sql

Changed
=======

Upload limit changed to 16 kB to accommodate larger profiles.

FlowSequencer events are now notified over ``SequencerGateNotification``
and include a ``sequence_id`` and the ``active_state`` for use with
history logging.

``Profile.from_json()`` now expects a string or bytes-like object,
rather than a dict. This change is to ease capture of the profile
"source" for use with history logging.

``ProfileByFrames.from_json()`` no longer rounds the floats to maintain
the integrity of the original source. They will still be rounded at the
time that they are encoded into binary payloads.

Standard initialization of the DE1 now includes reading
``CUUID.Versions`` and ``ShotSettings`` to speed first-time store of
profiles.

Robustness of shutdown improved.

Internal ``Profile`` class extended to capture "raw source", metadata,
and UUIDs for both the raw source and the resulting "program" sent to
the DE1.

Fixed
=====

In ``find_first_and_load.py``, ``set_saw()`` now uses the passed mass

Deprecated
==========

``Profile.from_json_file()`` as it is no longer needed with the API able
to upload profiles. If needed within the code base, read the file, and
pass to ``Profile.from_json()`` to ensure that the profile source and
signatures are properly updated.

``DE1._recorder_active`` and the contents of ``shot_file.py`` have been
superseded by database logging.

Known Issues
============

The database name is hard-coded at this time.

``Profile.regenerate_source()`` is not implemented at this time.

Occasionally, during shutdown, the database capture reports that it was
passed ``None`` and an exception is raised. This may be due to shut
down, or may be due to failure to retrieve an earlier exception from the
task.


------------------
0.5.0 – 2021-07-14
------------------

New
===

Bluetooth scanning with API. See ``README.bluetooth.md`` for details

API can set scale and DE1 by ID, by first\_if\_found, or None

A list of logs and individual logs can be obtained with GET
``Resource.LOGS`` and ``Routine.LOG``

``ConnectivityEnum.READY`` added, allowing clients to clearly know if
the DE1 or scale is available for use.

.. warning::
   Previous code that assumed that ``.CONNECTED`` was the
   terminal state should be modified to recognize ``.READY``.

``examples/find_first_and_load.py`` demonstrates stand-alone connection
to a DE1 and scale, loading of a profile, setting of shot parameters,
and disconnecting from these devices.

``scale_factory(BLEDevice)`` returns an appropriate ``Scale`` subtype

``Scale`` subtypes need to register their advertisement-name prefix,
such as

::

    Scale.register_constructor(AtomaxSkaleII, 'Skale')

Timeout on ``await`` calls initiated by the API

Use of connecting to the first-found DE1 and scale, monitoring MQTT,
uploading a profile, setting SAW, all through the API is shown in
``examples/find_first_and_load.py``

Example profiles: EB6 has 30-s ramp vs EB5 at 25-s

Add ``timestamp_to_str_with_ms()`` to ``pyDE1.utils``

On an error return to the inbound API, an exception trace is provided,
when available. This is intended to assist in error reporting.


Changed
=======

HTTP API PUT/PATCH requests now return a list, which may be empty.
Results, if any, from individual setters are returned as dict/obj
members of the list.

Some config parameters moved into ``pyDE1.config.bluetooth``

"find\_first" functionality now implemented in ``pyDE1.scanner``

``de1.address()`` is replaced with ``await de1.set_address()`` as it
needs to disconnect the existing client on address change. It also
supports address change.

``Resource.SCALE_ID`` now returns null values when there is no scale.

There's not much left of ``ugly_bits.py`` as its functions now should be
able to be handled through the API.

On connect, if any of the standard register reads fails, it is logged
with its name, and retried (without waiting).

An additional example profile was added. EB6 has 30-s ramp vs EB5 at
25-s. Annoying rounding errors from Insight removed.

MAPPING 3.1.0
-----------------

Add Resource.SCAN and Resource.SCAN\_RESULTS

See note above on return results, resulting in major version bump

Add ``first_if_found`` key to mapping for ``Resource.DE1_ID`` and
``Resource.SCALE_ID``. If True, then connects to the first found,
without initiating a scan. When using this feature, no other keys may be
provided.

RESOURCE 2.0.0
------------------

.. note:
   Breaking change: ``ConnectivityEnum.READY`` added. See Commit
   ``b53a8eb`` Previous code that assumed that ``.CONNECTED`` was the
   terminal state should be modified to recognize ``.READY``.

Add

::

        SCAN = 'scan'
        SCAN_DEVICES = 'scan/devices'

::

        LOG = 'log/{id}'
        LOGS = 'logs'

Deprecated
==========

``stop_scanner_if_running()`` in favor of just calling
``scanner.stop()``

``ugly_bits.py`` for manual configuration now should be able to be
handled through the API. See ``examples/find_first_and_load.py``

Removed
=======

``READ_BACK_ON_PATCH`` removed as PATCH operations now can return
results themselves.

``device_adv_is_recognized_by`` class method on DE1 and Scale replaced
by registered prefixes

Removed ``examples/test_first_find_and_load.py``, use
``find_first_and_load.py``

Known Issues
============

At least with BlueZ, it appears that a connection request while scanning
will be deferred.

Implicit scan-for-address in the creation of a ``BleakClient`` does not
cache or report any devices it discovers. This does not have any
negative impacts, but could be improved for the future.


------------------
0.4.1 – 2021-07-04
------------------

Fixed
=====

Import problems with ``manual_setup`` resolved with an explicit
reference to the ``pyDE1.ugly_bits`` version. Local overrides that may
have been in use prior will likely no longer used. TODO: Provide a more
robust config system to replace this.

Non-espresso flow (hot water flush, steam, hot water) now have their
accumulated volume associated with Frame 0, rather than the last frame
number of the previous espresso shot.


------------------
0.4.0 – 2021-07-03
------------------

New
===

Support for non-GHC machines to be able to start flow through the API

More graceful shutdown on SIGINT, SIGQUIT, SIGABRT, and SIGTERM

Logging to a single file, ``/tmp/log/pyDE1/combined.log`` by default. If
changed to, for example, ``/var/log/pyDE1/``, the process needs write
permission for the directory.

.. note::
    Keeping the logs in a dedicated directory is suggested, as the
    plan is to provide an API where a directory list will be used to
    generate the ``logs`` collection. ``/tmp/`` is used for ease of
    development and is not guaranteed to survive a reboot.

Log file is closed and reopened on SIGHUP.

Long-running processes, tasks, and futures are supervised, with
automatic restart should they unexpectedly terminate. A limit of two
restarts is in place to prevent "thrashing" on non-transient errors.

Changed
=======

Exceptions moved into ``pyDE1.exceptions`` for cleaner imports into
child processes.

String-generation utilities moved from ``pyDE1.default_logger`` into
``pyDE1.utils``

-  ``data_as_hex()``
-  ``data_as_readable()``
-  ``data_as_readable_or_hex()``

Remove inclusion of ``pyDE1.default_logger`` and replace with explicit
calls to ``initialize_default_logger()`` and
``set_some_logging_levels()``

Change from ``asyncio-mqtt`` to "bare" ``paho-mqtt``. The
``asyncio-mqtt`` module is still a requirement as it is used in
``examples/monitor_delay.py``

Controller now runs in its own process. Much of what was in
``try_de1.py`` is now in ``controller.py``

Log entries now include the process name.

IPC between the controller and outbound (MQTT) API now uses a pipe and
``loop.add_reader()`` to improve robustness and ease graceful shutdown.

Several internal method signatures changed to accommodate changes in
IPC. These are considered "internal" and do not impact the two, public
APIs.

Significant refactoring to move setup and run code out of ``try_de1.py``
and into more appropriate locations. The remaining "manual" setup steps
are now in ``ugly_bits.py``. See also ``run.py``

MAPPING 2.1.1
-----------------

-  Handle missing modules in "version" request by returning ``None``
   (``null``)

RESOURCE 1.2.0
------------------

-  Adds to ``DE1ModeEnum`` Espresso, HotWaterRinse, Steam, HotWater for
   use by non-GHC machines

-  ``.can_post`` now returns False, reflecting that POST is and was not
   supported

Response Codes
--------------

-  409 — When the current state of the device does not permit the action
-  ``DE1APIUnsupportedStateTransitionError``

-  418 — When the device is incapable of or blocked from taking the
   action
-  ``DE1APIUnsupportedFeatureError``

Fixed
=====

Resolved pickling errors related to a custom exception. It now is
properly reported to and by the HTTP server.

Changed BleakClient initialization to avoid
``AttributeError: 'BleakClientBlueZDBus' object has no attribute 'lower'``
and similar for ``'BleakClientCoreBluetooth'``

Exiting prior to device connection no longer results in
``AttributeError: 'NoneType' object has no attribute 'disconnect'``

Deprecated
==========

``try_de1.py`` is deprecated in favor of ``run.py`` or similar
three-liners.

Removed
=======

"null" outbound API implementation — Removed as not refactored for new
IPC. If there is a need, the MQTT implementation can be modified to only
consume from the pipe and not create or use an MQTT client.

Known Issues
============

Exceptions on a non-supervised task or callback are "swallowed" by the
default handler. They are reported in the log, but do not terminate the
caller.

The API for enabling and disabling auto-tare and stop-at can only do so
within the limits of the FlowSequencer's list of applicable states. See
further ``autotare_states``, ``stop_at_*_states``, and
``last_drops_states``

The main process can return a non-zero code even when the shutdown
appeared to be due to a shutdown signal, rather than an exception.

The hard limit of two restarts should be changed to a time-based limit.


------------------
0.3.0 — 2021-06-26
------------------

New
===

Upload of profile (JSON "v2" format) available with PUT at de1/profile

    curl -D - -X PUT --data @examples/jmk\_eb5.json
    http://localhost:1234/de1/profile

Line frequency GET/PATCH at de1/calibration/line\_frequency implemented.
Valid values are 50 or 60. This does not impact the DE1, only if 1/100
or 1/120 is used to calculate volume dispensed.

The HTTP API now checks to see if the request can be serviced with the
current DE1 and Scale connectivity. This should help enable people that
don't have a Skale II connected.

.. note:
    Although the DE1 and Scale can be reconnected, they are not
    reinitialized at this time.

``BleakClientWrapped.willful_disconnect`` property can be used to
determine if the on-disconnect callback was called as a result of an
intentional (locally initiated) or unintentional disconnect.

``BleakClientWrapped.name`` provides the advertised device name under
BlueZ and should not fail under macOS (or Windows).

Changed
=======

MAPPING 2.1.0
-----------------

-  Adds ``IsAt.internal_type`` to help validate the string values for
   ``DE1ModeEnum`` and ``ConnectivityEnum``. JSON producers and
   consumers should still expect and provide ``IsAt.v_type``

-  Enables ``de1/profile`` for PUT

RESOURCE 1.1.0
------------------

-  Adds
   ``DE1_CALIBRATION_LINE_FREQUENCY = 'de1/calibration/line_frequency'``

``DE1``, ``FlowSequencer``, and ``ScaleProcessor`` are now
``Singleton``.

``DE1()`` and ``Scale()`` no longer accept an address as an argument.
Use the ``.address`` property.

``BleakClientWrapped`` unifies ``atexit`` to close connected devices.

Fixed
=====

Better error reporting if the JSON value can not be converted to the
internal enum.

Python 3.8 compatibility: Changed "subscripted" type hints for ``dict``,
``list``, and ``set`` to their capitalized versions from ``typing``,
added replacement for ``str.removeprefix()``

Running on macOS with ``bleak`` 0.12.0 no longer raises device-name
lookup errors. This was not a ``bleak`` issue, but due to hopeful access
to its private internals.

Removed
=======

``DE1()`` and ``Scale()`` no longer accept an address as an argument.
Use the ``.address`` property.


------------------
0.2.0 — 2021-06-22
------------------

Inbound Control and Query API
=============================

An inbound API has been provided using a REST-like interface over HTTP.
The API should be reasonably complete in its payload and method
definitions and comments are welcomed on its sufficiency and
completeness.

Both the inbound and outbound APIs run in separate *processes* to reduce
the load on the controller itself.

GET should be available for the registered resources. See, in
``src/pyDE1/dispatcher``

-  ``resource.py`` for the registered resources, and
-  ``mapping.py`` for the elements they contain, the expected value
   types, and how they nest.

``None`` or ``null`` are often used to me "no value", such as for
stop-at limits. As a result, though similar, this is not an `RFC7368
JSON Merge Patch <https://datatracker.ietf.org/doc/html/rfc7386>`__.

In Python notation, ``Optional[int]`` means an ``int`` or ``None``.
Where ``float`` is specified, a JSON value such as ``20`` is permitted.

GET presently returns "unreadable" values to be able to better show the
structure of the JSON. When a value is unreadable, ``math.nan`` is used
internally, which is output as the JSON ``NaN`` token.

GET also returns empty nodes to illustrate the structure of the
document. This can be controlled with the ``PRUNE_EMPTY_NODES`` variable
in ``implementation.py``

Although PATCH has been implemented for most payloads, PUT is not yet
enabled. PUT will be the appropriate verb for\ ``DE1_PROFILE`` and
``DE1_FIRMWARE`` as, at this time, in-place modification of these is not
supported. The API mechanism for starting a firmware upload as not been
determined, as it should be able to abort as it runs in the background,
as well as notify when complete. Profile upload is likely to be similar,
though it occurs on a much faster timescale.

If you'd like the convenience of a GET of the same resource after a
PATCH, you can set ``READ_BACK_ON_PATCH`` to ``True`` in
``dispacher.py``

    The Python ``http.server`` module is used. It is not appropriate for
    exposed use. There is no security to the control and query API at
    this time. See further
    https://docs.python.org/3/library/http.server.html

It is likely that the server, itself, will be moved to a uWSGI (or
similar) process.

With either the present HTTP implementation or a future uWSGI one, use
of a webserver, such as ``nginx``, will be able to provide TLS,
authentication, and authorization, as well as a more "production-ready"
exposure.

Other Significant Changes
=========================

-  ``ShotSampleWithVolumeUpdates`` (v1.1.0) adds ``de1_time``.
   ``de1_time`` and ``scale_time`` are preferred over ``arrival_time``
   as, in a future version, these will be estimates that remove some of
   the jitter relative to packet-arrival time.

-  To be able to keep cached values of DE1 variables current, a
   read-back is requested on each write.

-  ``NoneSet`` and ``NONE_SET`` added to some ``enum.IntFlag`` to
   provide clearer representations

-  Although ``is_read_once`` and ``is_stable`` have been roughed in,
   optimizations using them have not been done

-  Disabled reads of ``CUUID.ReadFromMMR`` as it returns the request
   itself, which is not easily distinguishable from the data read. These
   two interpret their ``Length`` field differently, making it difficult
   to determine if ``5`` is an unexpected value or if it was just that 6
   words were requested to be read.

-  Scaling on ``MMR0x80LowAddr.TANK_WATER_THRESHOLD`` was corrected.


------------------
0.1.0 — 2021-06-11
------------------

Outbound API
============

An outbound API (notifications) is provided in a separate process. The
present implementation uses MQTT and provides timestamped,
source-identified, semantically versioned JSON payloads for:

-  DE1

   -  Connectivity
   -  State updates
   -  Shot samples with accumulated volume
   -  Water levels

-  Scale

   -  Connectivity
   -  Weight and flow updates

-  Flow sequencer

   -  "Gate" clear and set

      -  Sequence start
      -  Flow begin
      -  Expect drops
      -  Exit preinfuse
      -  Flow end
      -  Flow-state exit
      -  Last drops
      -  Sequence complete

   -  Stop-at-time/volume/weight

      -  Enable, disable (with target)
      -  Trigger (with target and value at trigger)

An example subscriber is provided in ``examples/monitor_delay.py``. On a
Raspberry Pi 3B, running Debian *Buster* and ``mosquitto`` 2.0 running
on ``::``, median delays are under 10 ms from *arrival\_time* of the
triggering event to delivery of the MQTT packet to the subscriber.

Packets are being sent with *retain* True, so that, for example, the
subscriber has the last-known DE1 state without having to wait for a
state change. Checking the payload's ``arrival_time`` is suggested to
determine if the data is fresh enough. The *will* feature of MQTT has
not yet been implemented.

A good introduction to MQTT and MQTT 5 can be found at HiveMQ:

-  https://www.hivemq.com/mqtt-essentials/
-  https://www.hivemq.com/blog/mqtt5-essentials-part1-introduction-to-mqtt-5/

One good thing about MQTT is that you can have as many subscribers as
you want without slowing down the controller. For example, you can have
a live view on your phone, live view on your desktop, log to file, log
to database, all at once.

Scan For And Use First DE1 And Skale Found
==========================================

Though "WET" and needing to be "DRY", the first-found DE1 and Skale will
be used. The Scale class has already been designed to be able to have
each subclass indicate if it recognizes the advertisement. Once DRY, the
scanner should be able to return the proper scale from any of the
alternatives.

Refactoring of this is pending the formal release of
``BleakScanner.find_device_by_filter(filterfunc)`` from `bleak PR
#565 <https://github.com/hbldh/bleak/pull/565>`__
