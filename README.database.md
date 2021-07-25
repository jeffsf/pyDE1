# Profile And History Database

## Status - RFC

### Revision History

* 2021-07-15 – Initial draft

## Design Objectives

### Primary

No data loss, within reason. Though not down to the raw, Bluetooth-packet 
level, all data that would have been delivered to an API consumer 
should be available for replay. 

Provide an output format that is compatible with Miha Rikar's Visualizer
[code](https://github.com/miharekar/decent-visualizer) 
and [service](https://visualizer.coffee).

Allow concurrent access from other applications.

Allow for extension of the schema to meet the needs of other applications,
such as Enrique Bengoechea's 
[Describe Your Espresso](https://github.com/ebengoechea/de1app_plugin_DYE).

Provide schema upgrades that are transparent to end users.

Does not interfere meaningfully with a shot in progress. 
Target is less than 1 ms of additional delay during shots.

### Secondary

Be able to uniquely identify the core of the profile 
(that which is sent to the machine) globally, independent of the 
name, format, or metadata associated with it.

## Candidate Approach

### SQLite3 Selected

During recording, with a Bluetooth-connected DE1 and scale, approximately 
15 MQTT packets per second are sent. This seems to be well within 
the capabilities of SQLite3 on a modest processor. Concurrent access for 
[SQLite3 with write-ahead logging](https://www.sqlite.org/wal.html) 
handles modest concurrency requirements well. It is now "old news" 
and has been shaken out with its use in Android. SQLite3 also offers 
significant benefits in ease of configuration and 
footprint over options such as MariaDB.

#### Time Values

Time values are all Unix timestamps. 

> NB: SQLite3 
[Date And Time Functions](https://www.sqlite.org/lang_datefunc.html) 
do not work directly with Unix timestamps. Care needs to be taken 
> if using these functions.

```
sqlite> select strftime('%Y-%m-%d %H:%M:%S', 1627242268.123, 'unixepoch');
2021-07-25 19:44:28
sqlite> select strftime('%Y-%m-%d %H:%M:%f', 1627242268.123, 'unixepoch');
2021-07-25 19:44:28.123
```

### Profiles

"Profiles" presently consist of a file that contains data that:

* Is transformed into the frames sent to the DE1
* May be used to set other registers in the DE1 
* May be used to set controller parameters outside of the DE1
* Contains metadata about the profile that does not impact operation

By the time the "profile" gets to the controller, there is no notion of 
"filename". For better or worse, this avoids the problems of the 
filename being used as the unique identifier for the profile. 

#### Unique Identifier for Profile "File" (Source)

We need a primary key for the "profile", both for reference by recorded shots,
as well as for referencing "extension" data.

The average profile size is presently in the 4-6 kB range. At this size, 
either MD5 or SHA1 running Python3 on an RPi 3B can calculate a hash 
in under 50 µs. Moving up to 16 kB, there is less advantage to the MD5, 
with both around 100 µs. As the additional time for the SHA1 hash over MD5
is small and has potential benefits in other areas, SHA1, as hex digits, 
will be used to uniquely identify the *raw source bytestream* 
containing this data set.

It is not always the case that a profile had a "source file". 
They conceivably can be generated on-the-fly, such as a future "internal" 
that raises or lowers the temperatures of each frame. 
When this becomes a reality, `Profile.regenerate_source()` will need 
an implementation and to be called appropriately.

#### Unique Identifier for Profile "Instruction Set"

Two profile sources may result in the same set of instructions, 
either for a single user or across users. As the data is available to make
a "global identifier" and it is expected to be under 10 µs to calculate, 
might as well, even if not immediately useful.

With the current, frame-based profiles, there are conceptually 
two sets of data.
There is the `ShotDescHeader`, then several frames of various types, 
`ShotFrame`, `ShotExtFrame`, and `ShotTail`

There are also parameters that are present in the current, JSON representation
that impact other DE1 settings, such as tank_temperature. As these can be 
changed independently of the "instruction set", they are not included. 
Metadata that is managed outside of the DE1 firmware, such as stop-at limits, 
as well as name, author, description, ... , are also not included. 
This data will be referenced to the profile source, as well as to the 
sequence record (as it can change independently of the profile instructions).

To calculate the "fingerprint" of the profile's instruction set, 
for frame-based profiles:

* Convert the profile into the `ShotDescHeader`, `ShotFrame`, `ShotExtFrame`, 
  and `ShotTail` series to be sent.
* Concatenate the over-the-wire, binary payload of those 
  in the following order:
	* `ShotDescHeader`
	* `ShotFrame` in ascending order
	* `ShotExtFrame` in ascending order
	* `ShotTail`
* Take the SHA1 of the result, express as hex digits

Although the `ShotExtFrame` is "optional" if it is "empty" and 
should not change the operation of the system, the implementation here 
will be to use what is sent, neither adding or removing frames.


#### Candidate Schema – Profile

Data types are "text" unless otherwise noted

Primary Data

* id – primary key – SHA1 of source byte stream ("raw")
* source – blob – the byte stream of the "original source" 
  of the profile and metadata
* source_version – 'JSONv2'
* fingerprint – SHA1 of the profile frames, as described above, 
  for frame-based profiles (TBD for future "program" representations)
* date_added – Unix timestamp of record creation date/time
* 
Operational (Shot-Specific) Settings 

* tank_water_threshold – float
* stop_at_weight – float (nullable)
* stop_at_volume – float (nullable)
* ~~number_of_preinfuse_frames – integer~~ 
  (already uploaded in the `ShotDescHeader`)

Non-Operational Metadata

* title
* author
* notes
* beverage_type – text keys as consistent with DYE and Visualizer


### (Shot) Sequence

The plan is to collect the data for any sequence, so not limited to espresso.

With the sequence as "home base", it needs a unique key for the related data. 
Although the sequence-start time could be used, using a UUID will take 
a rather tiny chance of duplication to a near impossibility, 
even in global stores across hundreds or thousands of users.

As this table will likely be searched for shots, it should have 
enough information to be able to perform the most common searches 
without joins. Returning the N most-recent shots is essential.

#### Candidate Schema – Sequence

* id – UUID
* active_state
* start_sequence – float
* start_flow – float
* end_flow – float
* end_sequence – float
* profile_id – FK to Profile
* profile_assumed – 0 (FALSE) if not "confirmed" to be the one in the DE1
* resource_version – what a GET on Resource.VERSION would return (JSON)
* resource_de1_id
* resource_de1_read_once
* resource_de1_calibration_flow_multiplier
* resource_de1_mode
* resource_de1_control – mode specific, Resource.DE1_CONTROL_ESPRESSO, ...
* resource_de1_control_tank_water_threshold
* resource_de1_setting_before_flow
* resource_de1_setting_steam
* resource_de1_setting_target_group_temp
* resource_scale_id

## "Normal" Case

* Keep a rolling buffer of "before sequence" packets
* Sequence-start packet arrives
	* Create a history record with id, active_state, and start_sequence
		* Use the "last-known" profile ID, set the "assumed" flag 
		 (use "dummy" profile for fresh DB and no profile only uploaded)
		* Request profile load from DE1 (async, give history id)
* Request resource information from DE1 (async, give history id)
* Stop buffering and start capturing packets
* Add the packets from the rolling buffers to the database asynchronously
* Update the history record as sequence packets arrive

## Edge Cases

### Connected to DE1 But No Profile Uploaded Or Available

Can happen if the controller thread restarts or if a profile isn't uploaded 
before a shot is started (and the DE1 uses whatever was in its memory).

Assume the last uploaded profile, but mark as "assumed"

#### `persist_hkv`

A little scratchpad of header/key/value entries to persist 
the last-known profile to handle this edge case. 
*May* have additional uses in the future, but not intended to be 
a generic "settings" store. 
(TOML on the file system will probably be used for that in the future.)


### Sequence Didn't Start

*TODO or confirm*

Deal with start as if whatever first packet arrives starts, run from there.

At least the start time needs something set, or the shot isn't "searchable". 
Leave others null.

### Sequence Didn't End

*TODO or confirm*

Well damn.

Watch for the Idle state. No more than XX seconds into Idle.

No more than YYY seconds total.

Leave all nulls as nulls.





