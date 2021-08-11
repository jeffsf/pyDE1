-- Copyright © 2021 Jeff Kletsky. All Rights Reserved.
--
-- License for this software, part of the pyDE1 package, is granted under
-- GNU General Public License v3.0 only
-- SPDX-License-Identifier: GPL-3.0-only

-- NB: This does not check schema version prior to execution

PRAGMA user_version = 2;

BEGIN TRANSACTION;

ALTER TABLE connectivity_change ADD COLUMN id TEXT;
ALTER TABLE connectivity_change ADD COLUMN name TEXT;

END TRANSACTION;


