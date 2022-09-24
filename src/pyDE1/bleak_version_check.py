""""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

The BlueZ stack will keep a connection to the device open even if Python exits.
This wrapper "automatically" adds an atexit close of the connection, as well as
trying to remove that atexit command if the object's __del__ method gets called.

There is only a handful of these at any one time. Using the atexit handler
with unique calls for each should be sufficient, rather than managing a list.
"""

# Starting with bleak v0.18.0, the method signature changed
# for BleakScanner.find_device_by_filter()
# https://github.com/hbldh/bleak/issues/1028

BLEAK_AFTER_0_17 = False

from bleak import __version__ as bleak_version
bvs = bleak_version.split('.', 4)
bleak_major = 0
bleak_minor = 0
bleak_patch = 0
try:
    bleak_major = int(bvs[0])
    bleak_minor = int(bvs[1])
    bleak_patch = int(bvs[2])
except IndexError:
    pass
if int(bleak_major) > 0 or (int(bleak_major) == 0 and (bleak_minor) > 17):
    BLEAK_AFTER_0_17 = True

