# Changelog

## 0.7.0 – 2021-08-12

### Schema Upgrade Required

> NB: Backup your database before updating the schema. 

See SQLite `.backup` for details if you are not familiar.

This adds columns for the `id` and `name` fields that are now being sent
with `ConnectivityUpdate` 

### New

* Stand-alone app automatically uploads to Visualizer on shot completion
* PUT and GET of DE1_PROFILE_ID allows setting of profile by ID
* A stand-alone "replay" utility can be used to exercise clients, 
	such as web apps
* Both the DE1 and scale will try to reconnect on unexpected disconnect
* Add `DE1IncompleteSequenceRecordError` for when write is not yet complete
* Variants of the EB6 profile at different temperatures 

### Fixed

* Legacy "shot" files handle zero flow in "resistance" calculation
* Properly end recording of a sequence if it is interrupted
* FlowSequencer last-drops gate set during sequence
* Correct logic error in stopping recorder at end of sequence
* Correct reporting of not-connected conditions to HTTP API
* Correct scale-presence checking for PUT and PATCH requests
* Handle missing Content-Length header
* Incorrect error message around API request for Sleep removed
* `pyDE1.scanner` should now import properly into other code
* Steam-temperature setter now can set 140-160 deg. C
* Type errors in validation of API inputs properly report the expected type

### Changed

* Better logging when waiting for a sequence to complete times out
* Capture pre-sequence history at all times so "sync" is possible on replay
* Removed read-back of CUUID.RequestedState as StateInfo 
  provides current state
* Removed "extra" last-drops check
* Allow more API requests when DE1 or scale is not ready
* Use "ready" and not just "connected" to determine if the 
	DE1 or scale can be queried
* Allow [dis]connect while [dis]connected
* `ConnectivityChange` notification includes `id` and `name` to remove 
	the need to call the API for them
* Improve error message on JSON decode by including a snippet 
  around the error
* Set the default first-drops threshold to 0.0 for fast-flowing shots


#### Resource Version 3.0.0

* Changes previously unimplemented _UPLOAD to _ID
    
        DE1_PROFILE_ID
        DE1_FIRMWARE_ID

#### Database Schema 2

See `upgrade.001.002.sql`

```
PRAGMA user_version = 2;

BEGIN TRANSACTION;

ALTER TABLE connectivity_change ADD COLUMN id TEXT;
ALTER TABLE connectivity_change ADD COLUMN name TEXT;

END TRANSACTION;
```


## 0.6.0 – 2021-07-25

**The Mimoja Release**

> I am not sure how / where to store shots and profiles. 
> I hate it to only have it browser local.

*So do I. Wonder no longer.*


### New

A SQLite3 database now saves all profiles uploaded to the DE1,
as well as capturing virtually all real-time data during all flow sequences,
including a brief set of data from *before* the state transition.

Profiles are unique by the content of their "raw source" and also have
a "fingerprint" that is common across all profiles that produce 
the same "program" for the DE1. Changing a profile's name alone 
does not change this fingerprint. Changing the frames in a profile
without changing the name changes both the ID of the profile,
as well as its fingerprint. These are both calculated using SHA1
from the underlying data, so should be consistent across installs
for the same source data or frame set. 

Profiles can also be searched by the customary metadata:

* Title
* Author
* Notes
* Beverage type
* Date added


`aiosqlite` and its dependencies are now required.

Legacy-style shot data can be extracted from the database by an application
other than that which is running the DE1. Creating a Visualizer-compatible 
"file" for upload can be done in around 80-100 ms on a RPi 3B. 
If written to a physical file, it is also compatible with John Weiss' 
shot-plotting programs. See `pyDE1/shot_file/legacy.py` 

The database retains the last-known profile uploaded to the DE1. 
If a flow sequence beings prior to uploading a profile, it is used 
as the "most likely" profile and identified in the database 
with the `profile_assumed` flag.

**NB: The database needs to be manually initialized prior to use.**

One approach is

```
sudo -u <user> sqlite3 /var/lib/pyDE1/pyDE1.sqlite3 \
< path/to/pyDE1/src/pyDE1/database/schema/schema.001.sql 

```

### Fixed

In `find_first_and_load.py`, `set_saw()` now uses the passed mass

### Changed

Upload limit changed to 16 kB to accommodate larger profiles.

FlowSequencer events are now notified over `SequencerGateNotification`
and include a `sequence_id` and the `active_state` 
for use with history logging.

`Profile.from_json()` now expects a string or bytes-like object, 
rather than a dict. This change is to ease capture of the 
profile "source" for use with history logging.

`ProfileByFrames.from_json()` no longer rounds the floats to maintain
the integrity of the original source. They will still be rounded 
at the time that they are encoded into binary payloads.

Standard initialization of the DE1 now includes reading `CUUID.Versions`
and `ShotSettings` to speed first-time store of profiles.

Robustness of shutdown improved.

Internal `Profile` class extended to capture "raw source", metadata, and UUIDs
for both the raw source and the resulting "program" sent to the DE1.

### Deprecated

`Profile.from_json_file()` as it is no longer needed with the API
able to upload profiles. If needed within the code base, read
the file, and pass to `Profile.from_json()` to ensure that
the profile source and signatures are properly updated.

`DE1._recorder_active` and the contents of `shot_file.py` have been 
superseded by database logging.

### Known Issues

The database name is hard-coded at this time.

`Profile.regenerate_source()` is not implemented at this time.

Occasionally, during shutdown, the database capture reports that
it was passed `None` and an exception is raised. This may be due to shut down,
or may be due to failure to retrieve an earlier exception from the task.


## 0.5.0 – 2021-07-14

### New

Bluetooth scanning with API. See `README.bluetooth.md` for details

API can set scale and DE1 by ID, by first_if_found, or None

A list of logs and individual logs can be obtained with GET
`Resource.LOGS` and `Routine.LOG`

`ConnectivityEnum.READY` added, allowing clients to clearly know if
the DE1 or scale is available for use.

> NB: Previous code that assumed that `.CONNECTED` was the terminal
  state should be modified to recognize `.READY`.

`examples/find_first_and_load.py` demonstrates stand-alone connection
to a DE1 and scale, loading of a profile, setting of shot parameters,
and disconnecting from these devices.

`scale_factory(BLEDevice)` returns an appropriate `Scale` subtype

`Scale` subtypes need to register their advertisement-name prefix,
such as

```
Scale.register_constructor(AtomaxSkaleII, 'Skale')
```

Timeout on `await` calls initiated by the API

Use of connecting to the first-found DE1 and scale, monitoring MQTT,
uploading a profile, setting SAW, all through the API is shown in
`examples/find_first_and_load.py`

Example profiles: EB6 has 30-s ramp vs EB5 at 25-s

Add `timestamp_to_str_with_ms()` to `pyDE1.utils`

On an error return to the inbound API, an exception trace is provided,
when available. This is intended to assist in error reporting.



### Fixed

### Changed

HTTP API PUT/PATCH requests now return a list, which may be
empty. Results, if any, from individual setters are returned as
dict/obj members of the list.

Some config parameters moved into `pyDE1.config.bluetooth`

"find_first" functionality now implemented in `pyDE1.scanner`

`de1.address()` is replaced with `await de1.set_address()` as it needs
to disconnect the existing client on address change. It also supports
address change.

`Resource.SCALE_ID` now returns null values when there is no scale.

There's not much left of `ugly_bits.py` as its functions now should be
able to be handled through the API.

On connect, if any of the standard register reads fails, it is logged
with its name, and retried (without waiting).

An additional example profile was added. EB6 has 30-s ramp vs EB5 at
25-s. Annoying rounding errors from Insight removed.

#### Mapping Version 3.1.0

Add Resource.SCAN and Resource.SCAN_RESULTS

See note above on return results, resulting in major version bump

Add `first_if_found` key to mapping for `Resource.DE1_ID` and
`Resource.SCALE_ID`. If True, then connects to the first found,
without initiating a scan. When using this feature, no other keys may
be provided.

#### Resource Version 2.0.0

> NB: Breaking change: `ConnectivityEnum.READY` added. See Commit b53a8eb
  Previous code that assumed that `.CONNECTED` was the
  terminal state should be modified to recognize `.READY`.

Add

```
    SCAN = 'scan'
    SCAN_DEVICES = 'scan/devices'
```

```
    LOG = 'log/{id}'
    LOGS = 'logs'
```

### Deprecated

`stop_scanner_if_running()` in favor of just calling `scanner.stop()`

`ugly_bits.py` for manual configuration now should be able to be
handled through the API. See `examples/find_first_and_load.py`

### Removed

`READ_BACK_ON_PATCH` removed as PATCH operations now can return
results themselves.

`device_adv_is_recognized_by` class method on DE1 and Scale replaced
by registered prefixes

Removed `examples/test_first_find_and_load.py`, use `find_first_and_load.py`

### Known Issues

At least with BlueZ, it appears that a connection request while
scanning will be deferred.

Implicit scan-for-address in the creation of a `BleakClient` does not
cache or report any devices it discovers. This does not have any
negative impacts, but could be improved for the future.


## 0.4.1 – 2021-07-04

### Fixed

Import problems with `manual_setup` resolved with an explicit reference
to the `pyDE1.ugly_bits` version. Local overrides that may have been
in use prior will likely no longer used. TODO: Provide a more robust
config system to replace this.

Non-espresso flow (hot water flush, steam, hot water) now have their
accumulated volume associated with Frame 0, rather than the last frame
number of the previous espresso shot.


## 0.4.0 – 2021-07-03

### New

Support for non-GHC machines to be able to start flow through the API

More graceful shutdown on SIGINT, SIGQUIT, SIGABRT, and SIGTERM

Logging to a single file, `/tmp/log/pyDE1/combined.log` by default. If
changed to, for example, `/var/log/pyDE1/`, the process needs write
permission for the directory.

> NB: Keeping the logs in a dedicated directory is suggested, as the
  plan is to provide an API where a directory list will be used to
  generate the `logs` collection. `/tmp/` is used for ease of
  development and is not guaranteed to survive a reboot.

Log file is closed and reopened on SIGHUP.

Long-running processes, tasks, and futures are supervised, with
automatic restart should they unexpectedly terminate. A limit of two
restarts is in place to prevent "thrashing" on non-transient errors.


### Fixed

Resolved pickling errors related to a custom exception. It now is
properly reported to and by the HTTP server.

Changed BleakClient initialization to avoid
`AttributeError: 'BleakClientBlueZDBus' object has no attribute 'lower'`
and similar for `'BleakClientCoreBluetooth'`

Exiting prior to device connection no longer results in
`AttributeError: 'NoneType' object has no attribute 'disconnect'`

### Changed

Exceptions moved into `pyDE1.exceptions` for cleaner imports into
child processes.

String-generation utilities moved from `pyDE1.default_logger` into
`pyDE1.utils`

* `data_as_hex()`
* `data_as_readable()`
* `data_as_readable_or_hex()`

Remove inclusion of `pyDE1.default_logger` and replace with explicit
calls to `initialize_default_logger()` and `set_some_logging_levels()`

Change from `asyncio-mqtt` to "bare" `paho-mqtt`. The `asyncio-mqtt`
module is still a requirement as it is used in
`examples/monitor_delay.py`

Controller now runs in its own process. Much of what was in
`try_de1.py` is now in `controller.py`

Log entries now include the process name.

IPC between the controller and outbound (MQTT) API now uses a pipe and
`loop.add_reader()` to improve robustness and ease graceful shutdown.

Several internal method signatures changed to accommodate changes in
IPC. These are considered "internal" and do not impact the two, public
APIs.

Significant refactoring to move setup and run code out of `try_de1.py`
and into more appropriate locations. The remaining "manual" setup
steps are now in `ugly_bits.py`. See also `run.py`

#### Mapping Version 2.1.1

* Handle missing modules in "version" request by returning `None` (`null`)

#### Resource Version 1.2.0

* Adds to `DE1ModeEnum` Espresso, HotWaterRinse, Steam, HotWater for
  use by non-GHC machines
  
* `.can_post` now returns False, reflecting that POST is and was not supported

#### Response Codes

* 409 — When the current state of the device does not permit the action
  * `DE1APIUnsupportedStateTransitionError`

* 418 — When the device is incapable of or blocked from taking the action
  * `DE1APIUnsupportedFeatureError`


### Deprecated

`try_de1.py` is deprecated in favor of `run.py` or similar three-liners.

### Removed

"null" outbound API implementation — Removed as not refactored for new
IPC. If there is a need, the MQTT implementation can be modified to
only consume from the pipe and not create or use an MQTT client.

### Known Issues

Exceptions on a non-supervised task or callback are "swallowed" by the
default handler. They are reported in the log, but do not terminate
the caller.

The API for enabling and disabling auto-tare and stop-at can only do
so within the limits of the FlowSequencer's list of applicable
states. See further `autotare_states`, `stop_at_*_states`, and
`last_drops_states`

The main process can return a non-zero code even when the shutdown
appeared to be due to a shutdown signal, rather than an exception.

The hard limit of two restarts should be changed to a time-based limit.

## 0.3.0 — 2021-06-26

### New

Upload of profile (JSON "v2" format) available with PUT at de1/profile

>  curl -D - -X PUT --data @examples/jmk_eb5.json  http://localhost:1234/de1/profile

Line frequency GET/PATCH at de1/calibration/line_frequency
implemented. Valid values are 50 or 60. This does not impact the DE1,
only if 1/100 or 1/120 is used to calculate volume dispensed.

The HTTP API now checks to see if the request can be serviced with the
current DE1 and Scale connectivity. This should help enable people
that don't have a Skale II connected.

> **NB: Although the DE1 and Scale can be reconnected, they are not
  reinitialized at this time.**

`BleakClientWrapped.willful_disconnect` property can be used to
determine if the on-disconnect callback was called as a result of an
intentional (locally initiated) or unintentional disconnect.

`BleakClientWrapped.name` provides the advertised device name under
BlueZ and should not fail under macOS (or Windows).

### Fixed

Better error reporting if the JSON value can not be converted to the
internal enum.

Python 3.8 compatibility: Changed "subscripted" type hints for `dict`,
`list`, and `set` to their capitalized versions from `typing`, added
replacement for `str.removeprefix()`

Running on macOS with `bleak` 0.12.0 no longer raises device-name
lookup errors. This was not a `bleak` issue, but due to hopeful access
to its private internals.

### Changed

#### Mapping Version 2.1.0

* Adds `IsAt.internal_type` to help validate the string values for
  `DE1ModeEnum` and `ConnectivityEnum`. JSON producers and consumers
  should still expect and provide `IsAt.v_type`
  
* Enables `de1/profile` for PUT

#### Resource Version 1.1.0

* Adds `DE1_CALIBRATION_LINE_FREQUENCY = 'de1/calibration/line_frequency'`


`DE1`, `FlowSequencer`, and `ScaleProcessor` are now `Singleton`.

`DE1()` and `Scale()` no longer accept an address as an argument. Use
the `.address` property.

`BleakClientWrapped` unifies `atexit` to close connected devices.

### Deprecated

### Removed

`DE1()` and `Scale()` no longer accept an address as an argument. Use
the `.address` property.


## 0.2.0 — 2021-06-22

### Inbound Control and Query API

An inbound API has been provided using a REST-like interface over
HTTP. The API should be reasonably complete in its payload and method
definitions and comments are welcomed on its sufficiency and
completeness.

Both the inbound and outbound APIs run in separate *processes* to
reduce the load on the controller itself.

GET should be available for the registered resources. See, in `src/pyDE1/dispatcher`

* `resource.py` for the registered resources, and
* `mapping.py` for the elements they contain, the expected value
  types, and how they nest.

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

If you'd like the convenience of a GET of the same resource after a
PATCH, you can set `READ_BACK_ON_PATCH` to `True` in `dispacher.py`

> The Python `http.server` module is used. It is not appropriate for exposed use.
> There is no security to the control and query API at this time.
> See further https://docs.python.org/3/library/http.server.html

It is likely that the server, itself, will be moved to a uWSGI (or
similar) process.

With either the present HTTP implementation or a future uWSGI one, use
of a webserver, such as `nginx`, will be able to provide TLS,
authentication, and authorization, as well as a more
"production-ready" exposure.


### Other Significant Changes

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
  itself, which is not easily distinguishable from the data
  read. These two interpret their `Length` field differently, making
  it difficult to determine if `5` is an unexpected value or if it was
  just that 6 words were requested to be read.
  
* Scaling on `MMR0x80LowAddr.TANK_WATER_THRESHOLD` was corrected.


## 0.1.0 — 2021-06-11

### Outbound API

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

### Scan For And Use First DE1 And Skale Found

Though "WET" and needing to be "DRY", the first-found DE1 and Skale
will be used. The Scale class has already been designed to be able to
have each subclass indicate if it recognizes the advertisement. Once
DRY, the scanner should be able to return the proper scale from any of
the alternatives.

Refactoring of this is pending the formal release of
`BleakScanner.find_device_by_filter(filterfunc)` from 
[bleak PR #565](https://github.com/hbldh/bleak/pull/565)
