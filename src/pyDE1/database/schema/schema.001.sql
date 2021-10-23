-- Copyright © 2021 Jeff Kletsky. All Rights Reserved.
--
-- License for this software, part of the pyDE1 package, is granted under
-- GNU General Public License v3.0 only
-- SPDX-License-Identifier: GPL-3.0-only

-- Schema version 1
-- TODO: How to detect current schema, run upgrade triggers,
--       and then set PRAGMA user_version

-- RAISE only available as a trigger
--
-- CREATE TEMPORARY VIEW IF NOT EXISTS _schema_check AS SELECT NULL AS val;
-- CREATE TEMPORARY TRIGGER _schema_check_0
--     INSTEAD OF INSERT ON _schema_check
--     BEGIN
--         SELECT RAISE(ROLLBACK, 'Expecting schema 0, rollback')
--             WHERE NEW.val != 0;
--     END;
--
-- Unfortunately no pragma_user_version()

-- PRAGMA user_version;

PRAGMA journal_mode=WAL;
-- Default checkpoint threshold is 1000 pages of 4096 bytes each
-- See https://sqlite.org/wal.html


BEGIN TRANSACTION;

PRAGMA user_version = 1;

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

CREATE INDEX idx_profile_fingerprint ON profile(fingerprint);
CREATE INDEX idx_profile_date_added ON profile(date_added);
CREATE INDEX idx_profile_title ON profile(title);
CREATE INDEX idx_profile_beverage_type ON profile(beverage_type);

-- Initial driver is "last-uploaded profile"
CREATE TABLE persist_hkv (
    header  TEXT,
    key     TEXT NOT NULL,
    value   TEXT
);

CREATE UNIQUE INDEX idx_persist_hkv_hk
    ON persist_hkv(header, key);

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

CREATE INDEX idx_sequence_active_state ON sequence (active_state);
CREATE INDEX idx_sequence_start_sequence ON sequence (start_sequence);
CREATE INDEX idx_sequence_start_flow ON sequence (start_flow);
CREATE INDEX idx_sequence_end_flow ON sequence (end_flow);
CREATE INDEX idx_sequence_end_sequence ON sequence (end_sequence);
CREATE INDEX idx_sequence_profile_id ON sequence (profile_id);

-- pyDE1/ShotSampleWithVolumesUpdate {"arrival_time": 1626486527.384532,
-- "create_time": 1626486527.3852458, "sample_time": 26721,
-- "group_pressure": 0.0, "group_flow": 0.0, "mix_temp": 23.66796875,
-- "set_mix_temp": 89.0, "set_head_temp": 89.0, "set_group_pressure": 0.0,
-- "set_group_flow": 6.0, "frame_number": 4, "steam_temp": 32,
-- "de1_time": 1626486527.384532, "volume_preinfuse": 0,
-- "volume_pour": 0, "volume_total": 0, "volume_by_frames": [],
-- "version": "1.1.0", "event_time": 1626486527.385474,
-- "sender": "DE1", "class": "ShotSampleWithVolumesUpdate"}

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

CREATE INDEX idx_shot_sample_with_volume_update_sequence_id
    ON shot_sample_with_volume_update(sequence_id);

-- pyDE1/WeightAndFlowUpdate {"arrival_time": 1626486527.5268447,
-- "create_time": 1626486527.5291858, "scale_time": 1626486527.1468446,
-- "current_weight": -140.0, "current_weight_time": 1626486526.7168446,
-- "average_flow": 0.0, "average_flow_time": 1626486526.244476,
-- "median_weight": -140.0, "median_weight_time": 1626486526.244476,
-- "median_flow": 0.0, "median_flow_time": 1626486525.9269369,
-- "version": "1.0.0", "event_time": 1626486527.5307076,
-- "sender": "ScaleProcessor", "class": "WeightAndFlowUpdate"}

CREATE TABLE weight_and_flow_update (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    scale_time          REAL,
    --
    current_weight      REAL,
    current_weight_time REAL,
    average_flow        REAL,
    average_flow_time   REAL,
    median_weight       REAL,
    median_weight_time  REAL,
    median_flow         REAL,
    median_flow_time    REAL
);

CREATE INDEX idx_weight_and_flow_update_sequence_id
    ON weight_and_flow_update(sequence_id);

-- pyDE1/StateUpdate {"arrival_time": 1626484390.7518158,
-- "create_time": 1626484390.7521193, "state": "Sleep",
-- "substate": "NoState", "previous_state": "NoRequest",
-- "previous_substate": "NoState", "is_error_state": false,
-- "version": "1.0.0", "event_time": 1626484390.752274,
-- "sender": "DE1", "class": "StateUpdate"}

CREATE TABLE state_update (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    state               TEXT,
    substate            TEXT,
    previous_state      TEXT,
    previous_substate   TEXT,
    is_error_state      TEXT
);

CREATE INDEX idx_state_update_sequence_id
    ON state_update(sequence_id);

-- pyDE1/SequencerGateNotification {"arrival_time": 1626546455.3941407,
-- "create_time": 1626546455.3945763, "name": "sequence_start",
-- "action": "clear", "sequence_id": "1c0ad339-7b46-4edc-961f-29bb664abe1f",
-- "active_state": "Espresso", "version": "1.1.0",
-- "event_time": 1626546469.2678514, "sender": "FlowSequencer",
-- "class": "SequencerGateNotification"}

CREATE TABLE sequencer_gate_notification (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    name                TEXT,
    action              TEXT,
    active_state        TEXT
    -- sequence_id         TEXT
);

CREATE INDEX idx_sequencer_gate_notification_sequence_id
    ON sequencer_gate_notification(sequence_id);


-- pyDE1/StopAtNotification {"arrival_time": 1626407781.443385,
-- "create_time": 1626407781.443385, "stop_at": "weight",
-- "action": "triggered", "target_value": 50, "current_value": 49.0,
-- "active_state": "Espresso", "version": "1.0.0",
-- "event_time": 1626407781.443445, "sender": "NoneType",
-- "class": "StopAtNotification"}

CREATE TABLE stop_at_notification (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    stop_at             TEXT,
    action              TEXT,
    active_state        TEXT,
    target_value        REAL,
    current_value       REAL
);

CREATE INDEX idx_stop_at_notification_sequence_id
    ON stop_at_notification(sequence_id);

-- pyDE1/WaterLevelUpdate {"arrival_time": 1626486527.3875291,
-- "create_time": 1626486527.3877115, "level": 40.11328125,
-- "start_fill_level": 5.0, "version": "1.0.0",
-- "event_time": 1626486527.3878827, "sender": "DE1",
-- "class": "WaterLevelUpdate"}

CREATE TABLE water_level_update (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    level               REAL,
    start_fill_level    REAL
);

CREATE INDEX idx_water_level_update_sequence_id
    ON water_level_update(sequence_id);

-- pyDE1/ScaleTareSeen {"arrival_time": 1626407756.1907747,
-- "create_time": 1626407756.1930006, "version": "1.0.0",
-- "event_time": 1626407756.193286, "sender": "AtomaxSkaleII",
-- "class": "ScaleTareSeen"}

CREATE TABLE scale_tare_seen (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL
    --
);

CREATE INDEX idx_scale_tare_seen_sequence_id
    ON scale_tare_seen(sequence_id);


-- pyDE1/AutoTareNotification {"arrival_time": 1626407756.6536725,
-- "create_time": 1626407756.6536725, "action": "disabled",
-- "version": "1.0.0", "event_time": 1626407756.6537528,
-- "sender": "NoneType", "class": "AutoTareNotification"}

CREATE TABLE auto_tare_notification (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    action              TEXT
);

CREATE INDEX idx_auto_tare_notification_sequence_id
    ON auto_tare_notification(sequence_id);

-- pyDE1/ScaleButtonPress  {"arrival_time": 1626407564.4241736,
-- "create_time": 1626407564.4242156, "button": 1,
-- "version": "1.0.0", "event_time": 1626407564.5058796,
-- "sender": "AtomaxSkaleII", "class": "ScaleButtonPress"}

CREATE TABLE scale_button_press (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    button              INTEGER
);

CREATE INDEX idx_scale_button_press_sequence_id
    ON scale_button_press(sequence_id);

-- pyDE1/ConnectivityChange {"arrival_time": 1626484392.5182247,
-- "create_time": 1626484392.5182636, "state": "ready",
-- "version": "1.0.0", "event_time": 1626484392.5183613,
-- "sender": "AtomaxSkaleII", "class": "ConnectivityChange"}

CREATE TABLE connectivity_change (
    sequence_id         TEXT NOT NULL REFERENCES sequence (id),
    version             TEXT,
    sender              TEXT,
    arrival_time        REAL,
    create_time         REAL,
    event_time          REAL,
    --
    state               TEXT
);

CREATE INDEX idx_connectivity_change_sequence_id
    ON connectivity_change (sequence_id);

-- Need a "first-run" target for the FK if no profile ever uploaded
INSERT OR ROLLBACK INTO profile (id, source, source_format, fingerprint,
                                date_added) VALUES
                                ('dummy', 'dummy', 'dummy', 'dummy',
                                 0);

INSERT OR ROLLBACK INTO persist_hkv (header, key, value)
    VALUES ('last_profile', 'id', 'dummy');

INSERT OR ROLLBACK INTO persist_hkv (header, key, value)
    VALUES ('last_profile', 'datetime', 0);

INSERT OR ROLLBACK INTO sequence (id, profile_id) VALUES ('dummy', 'dummy');

COMMIT TRANSACTION;