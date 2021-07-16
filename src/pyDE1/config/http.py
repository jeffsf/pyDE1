"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Collected configuration parameters
"""
from pyDE1.config.bluetooth import SCAN_TIME, CONNECT_TIMEOUT

SERVER_HOST = ''
SERVER_PORT = 1234
SERVER_ROOT = '/'
PATCH_SIZE_LIMIT = 16384    # adaptive_allonge.json is 7632 bytes

ASYNC_TIMEOUT = 1.0     # Seconds, before abandoning the request
PROFILE_TIMEOUT = 4.5   # Seconds, 20*2 frames + head + tail at ~100 ms each

# See pyDE1/dispatcher/implementation.py
RESPONSE_TIMEOUT = SCAN_TIME + CONNECT_TIMEOUT + ASYNC_TIMEOUT + 0.100 + 0.100

# If true, don't output nodes that have no value (write-only)
# or are empty dicts
# Otherwise math.nan fills in for the missing value
# As not compliant with RFC 7159, some parsers may fail with NaN
# although it is permitted by ECMAScript and JavaScript
# A False setting is intended to be a development/exploration tool
# This feature be considered as deprecated
PRUNE_EMPTY_NODES = True
