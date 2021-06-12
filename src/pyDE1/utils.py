"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum
import logging
import re

import pyDE1.default_logger
logger_cancel_tasks = logging.getLogger('CancelTasks')


def task_name_exists(name_to_find: str, starts_with=False):
    all_tasks = asyncio.all_tasks()
    found = False
    for t in all_tasks:
        name = t.get_name()
        if starts_with:
            found = name.startswith(name_to_find)
        else:
            found = name == name_to_find
        if found:
            break
    return found


def cancel_tasks_by_name(name_to_cancel: str, starts_with=False):
    all_tasks = asyncio.all_tasks()
    me = asyncio.current_task()
    for t in all_tasks:
        if t is me:
            continue
        name = t.get_name()
        if starts_with:
            cancel = name.startswith(name_to_cancel)
        else:
            cancel = name == name_to_cancel
        if cancel:
            logger_cancel_tasks.info(f"Canceling {t}")
            t.cancel()


def address_is_persistent(address: str) -> bool:
    """
    CoreBluetooth uses a UUID rather than a MAC address to identify devices
    As a result, it is (probably) not persistent over reboots.
    """
    if re.match(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', address):
        return True
    else:
        # macOS UUIDs don't seem to be persistent across Mac reboots
        return False


def fix_enums(val):
    """
    Return the name of an IntEnum, does not help with IntFlag
    So far no IntFlag enums headed to the external API
    """
    # Order is important due to IntEnum and IntFlag behavior (including int)
    if val is None or isinstance(val, (float, str, bool)):
        return val
    elif isinstance(val, enum.IntFlag):
        # Remove the class name
        return str(val).split('.',2)[1]
    elif isinstance(val, enum.IntEnum):
        return val.name
    elif isinstance(val, enum.Enum):
        return val.value
    elif isinstance(val, (bytearray, bytes)):
        return val.hex()
    else:
        return val
