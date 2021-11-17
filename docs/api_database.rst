..
    Copyright © 2021 Jeff Kletsky. All Rights Reserved.

    License for this software, part of the pyDE1 package, is granted under
    GNU General Public License v3.0 only
    SPDX-License-Identifier: GPL-3.0-only

================
SQLite3 Database
================

The SQLite3 database primarily saves profiles and data related to sequences
(shots) with high fidelity. It also saves a few bits of persistent data,
such as the scale-period estimates. It is not intended to be a generic
settings store.

SQLite3 allows concurrent, multi-user access with `WAL mode`_. Additional
SQLite3 databases can be opened by other apps, allowing joins and other
operations between them.

.. note::

  When opening the database from another app or the command line, only
  use the *pyde1* user.

  Although other users have read access, failing to use the *pyde1* user
  may result in files being created that the *pyde1* user does not have
  write access to. This can cause "read-only" errors, even though the
  *pyde1* user has write access to the main database file.

.. _`WAL mode`: https://www.sqlite.org/wal.html

----------
Backing Up
----------

For any database, file-system backups may not result in a self-consistent
snapshot. Using the database's backup utility is highly recommended.

One approach is shown in this script

.. code-block:: sh

  #!/bin/sh

  filename=$(date +'/home/pyde1/db_backup/pyde1.%Y-%m-%d_%H%M.sqlite3')
  sqlite3 /var/lib/pyde1/pyde1.sqlite3 ".backup $filename"
  xz $filename

This can be run periodically by *pyde1* by editing the crontab with

::

  sudo -u pyde1 crontab -e

to add a line like

::

  00 03 * * * /home/pyde1/bin/pyde1-backup.sh

(Every day at 0300, local time)

------
Schema
------

The schema version is available as ``PRAGMA user_version``. The schema itself
is distributed at ``pyDE1/database/schema``.

Times are real values, such as would be returned by Python ``time.time()``

Sequences
=========

Most of the database is dedicated to capturing the notifications that are
generated immediately before and during a ``FlowSequencer`` sequence.

There is a rolling buffer that captures the most recent notifications that then
gets written to the database shortly after the start of a sequence.

Each sequence has a "master record" that is created at the start of the
sequence. Some fields are updated, such as times, are updated as the sequence
progresses. As this is done asynchronously, this record may not be complete
the instant the sequence ends.

.. code-block:: SQL

  CREATE TABLE sequence (
      id              TEXT NOT NULL PRIMARY KEY,
      active_state    TEXT,
      start_sequence  REAL,
      start_flow      REAL,
      end_flow        REAL,
      end_sequence    REAL,
      profile_id      TEXT NOT NULL REFERENCES profile(id),
      -- https://www.sqlite.org/quirks.html#no_separate_boolean_datatype
      profile_assumed INTEGER, -- will match TRUE and FALSE keywords
      resource_version                            TEXT,
      resource_de1_id                             TEXT,
      resource_de1_read_once                      TEXT,
      resource_de1_calibration_flow_multiplier    TEXT,
      resource_de1_control_mode                   TEXT,
      resource_de1_control_tank_water_threshold   TEXT,
      resource_de1_setting_before_flow            TEXT,
      resource_de1_setting_steam                  TEXT,
      resource_de1_setting_target_group_temp      TEXT,
      resource_scale_id                           TEXT
  );

Virtually all of the MQTT notifications are captured and associated with the
``sequence.id`` to allow for recreation of the data during the shot.
As an example

.. code-block:: SQL

  CREATE TABLE shot_sample_with_volume_update (
      sequence_id         TEXT NOT NULL REFERENCES sequence(id),
      version             TEXT,
      sender              TEXT,
      arrival_time        REAL,
      create_time         REAL,
      event_time          REAL,
      --
      de1_time            REAL,
      --
      sample_time         INTEGER,
      group_pressure      REAL,
      group_flow          REAL,
      mix_temp            REAL,
      head_temp           REAL,
      set_mix_temp        REAL,
      set_head_temp       REAL,
      set_group_pressure  REAL,
      set_group_flow      REAL,
      frame_number        INTEGER,
      steam_temp          REAL,
      --
      volume_preinfuse    REAL,
      volume_pour         REAL,
      volume_total        REAL,
      volume_by_frames    TEXT    -- Python list, default formatting
  );

Profiles
========

Profiles, uploaded through the HTTP API, get stored in the database, along
with their metadata. They are referenced by a unique ID over the uploaded
content, as well as indexed by a ``fingerprint`` of the frames that would be
delivered to the DE1. The same ``fingerprint`` is the same for the DE1,
but would be from different source data or have different metadata.

.. code-block:: SQL

  CREATE TABLE profile (
      id              TEXT NOT NULL PRIMARY KEY,
      source          BLOB NOT NULL,
      source_format   TEXT NOT NULL,
      fingerprint     TEXT NOT NULL,
      date_added      REAL,
      title           TEXT,
      author          TEXT,
      notes           TEXT,
      beverage_type   TEXT
  );

persist_hkv
===========

This is a small table used internally to persist time-varying data across
restarts of pyDE1 or connection and disconnection of devices. It should be
considered opaque and not part of the supported API.
