# Changelog

## Pending

### New

Support for non-GHC machines to be able to start flow through the API

More graceful shutdown on SIGINT, SIGQUIT, SIGABRT, and SIGTERM

Logging to a single file, `/tmp/log/pyDE1/combined.log` by default. If changed to, for example, `/var/log/pyDE1/`, the process needs write permission for the directory. 

> NB: Keeping the logs in a dedicated directory is suggested, as the plan is to provide an API where a directory list will be used to generate the `logs` collection. `/tmp/` is used for ease of development and is not guaranteed to survive a reboot. 

Log file is closed and reopened on SIGHUP.


### Fixed

Resolved pickling errors related to a custom exception. It now is properly reported to and by the HTTP server.

Changed BleakClient initialization to avoid
`AttributeError: 'BleakClientBlueZDBus' object has no attribute 'lower'` and similar for `'BleakClientCoreBluetooth'`

Exiting prior to device connection no longer results in `AttributeError: 'NoneType' object has no attribute 'disconnect'`

### Changed

Exceptions moved into `pyDE1.exceptions` for cleaner imports into child processes.

String-generation utilities moved from `pyDE1.default_logger` into `pyDE1.utils`

* `data_as_hex()`
* `data_as_readable()`
* `data_as_readable_or_hex()`

Remove inclusion of `pyDE1.default_logger` and replace with explicit calls to `initialize_default_logger()` and `set_some_logging_levels()`

Change from `asyncio-mqtt` to "bare" `paho-mqtt`. The `asyncio-mqtt` module is still a requirement as it is used in `examples/monitor_delay.py`

Controller now runs in its own process. Much of what was in `try_de1.py` is now in `controller.py`

Log entries now include the process name.

IPC between the controller and outbound (MQTT) API now uses a pipe and `loop.add_reader()` to improve robustness and ease graceful shutdown.

Several internal method signatures changed to accomodate changes in IPC. These are considered "internal" and do not impact the two, public APIs.

#### Mapping Version 2.1.1

* Handle missing modules in "version" request by returning `None` (`null`)

#### Resource Version 1.2.0

* Adds to `DE1ModeEnum` Espresso, HotWaterRinse, Steam, HotWater for use by non-GHC machines
* `.can_post` now returns False, reflecting that POST is and was not supported

#### Response Codes

* 409 — When the current state of the device does not permit the action
  * `DE1APIUnsupportedStateTransitionError`

* 418 — When the device is incapable of or blocked from taking the action
  * `DE1APIUnsupportedFeatureError`


### Deprecated


### Removed

**"null" outbound API implementation** — Removed as not refactored for new IPC. If there is a need, the MQTT implementation can be modified to only consume from the pipe and not create or use an MQTT client.


## 0.3.0 — 2021-06-26

### New

Upload of profile (JSON "v2" format) available with PUT at de1/profile

>  curl -D - -X PUT --data @examples/jmk_eb5.json  http://localhost:1234/de1/profile

Line frequency GET/PATCH at de1/calibration/line_frequency implemented. Valid values are 50 or 60. This does not impact the DE1, only if 1/100 or 1/120 is used to calculate volume dispensed.

The HTTP API now checks to see if the request can be serviced with the current DE1 and Scale connectivity. This should help enable people that don't have a Skale II connected.

> **NB: Although the DE1 and Scale can be reconnected, they are not reinitialized at this time.**

`BleakClientWrapped.willful_disconnect` property can be used to determine if the on-disconnect callback was called as a result of an intentional (locally initiated) or unintentional disconnect.

`BleakClientWrapped.name` provides the advertised device name under BlueZ and should not fail under macOS (or Windows).

### Fixed

Better error reporting if the JSON value can not be converted to the internal enum. 

Python 3.8 compatibility: Changed "subscripted" type hints for `dict`, `list`, and `set` to their capitalized versions from `typing`, added replacement for `str.removeprefix()`

Running on macOS with `bleak` 0.12.0 no longer raises device-name lookup errors. This was not a `bleak` issue, but due to hopeful access to its private internals. 

### Changed

#### Mapping Version 2.1.0 

* Adds `IsAt.internal_type` to help validate the string values for `DE1ModeEnum` and `ConnectivityEnum`. JSON producers and consumers should sill expect and provide `IsAt.v_type`
* Enables `de1/profile` for PUT

#### Resource Version 1.1.0

* Adds `DE1_CALIBRATION_LINE_FREQUENCY = 'de1/calibration/line_frequency'`


`DE1`, `FlowSequencer`, and `ScaleProcessor` are now `Singleton`.

`DE1()` and `Scale()` no longer accept an address as an argument. Use the `.address` property.

`BleakClientWrapped` unifies `atexit` to close connected devices. 

### Deprecated

### Removed

`DE1()` and `Scale()` no longer accept an address as an argument. Use the `.address` property.


## 0.2.0 — 2021-06-22

### Inbound Control and Query API

An inbound API has been provided using a REST-like interface over HTTP. The API should be reasonably complete in its payload and method definitions and comments are welcomed on its sufficiency and completeness.

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


### Other Significant Changes

* `ShotSampleWithVolumeUpdates` (v1.1.0) adds `de1_time`. `de1_time` and `scale_time` are preferred over `arrival_time` as, in a future version, these will be estimates that remove some of the jitter relative to packet-arrival time.

* To be able to keep cached values of DE1 variables current, a read-back is requested on each write. 
* `NoneSet` and `NONE_SET` added to some `enum.IntFlag` to provide clearer representations
* Although `is_read_once` and `is_stable` have been roughed in, optimizations using them have not been done
* Disabled reads of `CUUID.ReadFromMMR` as it returns the request itself (which is not easily distinguishable from the data read. These two interpret their `Length` field differently, making it difficult to determine if `5` is an unexpected value or if it was just that 6 words were requested to be read.
* Scaling on `MMR0x80LowAddr.TANK_WATER_THRESHOLD` was corrected.


## 0.1.0 — 2021-06-11

### Outbound API

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

### Scan For And Use First DE1 And Skale Found

Though "WET" and needing to be "DRY", the first-found DE1 and Skale will be used. The Scale class has already been designed to be able to have each subclass indicate if it recognizes the advertisement. Once DRY, the scanner should be able to return the proper scale from any of the alternatives. 

Refactoring of this is pending the formal release of `BleakScanner.find_device_by_filter(filterfunc)` from [bleak PR #565](https://github.com/hbldh/bleak/pull/565)
