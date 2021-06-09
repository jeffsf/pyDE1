"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import logging
import re

import pyDE1.default_logger
logger_cancel_tasks = logging.getLogger('CancelTasks')


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