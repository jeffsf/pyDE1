"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

On Linux, Bluetooth devices are not "cleaned up" by the OS when a process exits.
Although both the bleak library and this code attempts to ensure that they
are not left in a connected state by the OS's BlueZ stack, there are conditions
when this may still happen, such as SIGKILL or low-level faults. On relaunch,
these devices generally will not be advertising (as they are connected) and
can't be connected.

These functions manage files in config.bluetooth.ID_FILE_DIRECTORY, suffixed by
config.bluetooth.ID_FILE_SUFFIX, that may be used by a supervisory script
to disconnect any that remain connected.

After extracting the device ID from the file and properly sanitizing it,

    bluetoothctl disconnect D9:B2:48:aa:bb:cc

can run by a member of the bluetooth group to disconnect the device.

"""

import os
import re
import sys
from pathlib import Path

from pyDE1.config import config

re_nonhex = re.compile('[^0-9a-fA-F]')


def filename_from_id(id: str) -> Path:
    if id is None:
        raise ValueError("Attempt to persist None as Bluetooth ID")
    suffix = config.bluetooth.ID_FILE_SUFFIX
    fname = re.sub(re_nonhex, '', id)
    # This is only "active" for Linux, so expect 12, hex characters
    if len(fname) != 12:
        raise ValueError(
            f"Hex-filtered ID '{fname}' from '{id}' is not 12 characters")
    if not suffix.startswith('.'):
        suffix = '.' + suffix
    return Path(config.bluetooth.ID_FILE_DIRECTORY, fname + suffix)


def persist_connection_file(id: str):
    if sys.platform != 'linux':
        return
    with open(filename_from_id(id), 'w') as fh:
        print(id, file=fh, end='')


def remove_connection_file(id: str):
    if sys.platform != 'linux':
        return
    try:
        os.remove(filename_from_id(id))
    except FileNotFoundError:
        pass
