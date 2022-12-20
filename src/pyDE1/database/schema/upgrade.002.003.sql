-- Copyright © 2022 Jeff Kletsky. All Rights Reserved.
--
-- License for this software, part of the pyDE1 package, is granted under
-- GNU General Public License v3.0 only
-- SPDX-License-Identifier: GPL-3.0-only

-- NB: This does not check schema version prior to execution

BEGIN TRANSACTION;

CREATE TABLE device_availability (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    state               TEXT,
    id                  TEXT,
    name                TEXT,
    role                TEXT
);

CREATE INDEX idx_device_availability_sequence_id
    ON device_availability (sequence_id);

CREATE TABLE scale_change (
    sequence_id         TEXT,
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    state               TEXT,
    id                  TEXT,
    name                TEXT
);

CREATE INDEX idx_scale_change_sequence_id
    ON scale_change (sequence_id);

CREATE TABLE bluedot_update (
    sequence_id         TEXT,
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    temperature         REAL,
    high_alarm          REAL,
    units               TEXT,
    alarm_byte          INT,
    name                TEXT
);

CREATE INDEX idx_bluedot_update_sequence_id
    ON bluedot_update (sequence_id);

PRAGMA user_version = 3;

END TRANSACTION;




