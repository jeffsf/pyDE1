"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Message definitions for database/write_notifications queue
to break cyclical imports
"""
from typing import NamedTuple


class RecorderControl (NamedTuple):
    recording: bool
    sequence_id: str
