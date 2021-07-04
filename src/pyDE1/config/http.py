"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Collected configuration parameters
"""

SERVER_HOST = ''
SERVER_PORT = 1234
SERVER_ROOT = '/'
PATCH_SIZE_LIMIT = 4096

ASYNC_TIMEOUT = 1.0  # Seconds, before abandoning the request

# If true, don't output nodes that have no value (write-only)
# or are empty dicts
# Otherwise math.nan fills in for the missing value
# Should be considered as deprecated
PRUNE_EMPTY_NODES = False
