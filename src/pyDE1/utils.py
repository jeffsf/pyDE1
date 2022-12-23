"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum
import logging
import multiprocessing
import queue
import re
import sys
import time
import uuid

from datetime import datetime
from typing import Optional, Union

logger_cancel_tasks = logging.getLogger('Util.CancelTasks')


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


if sys.version_info.major >= 3 and sys.version_info.minor >= 11:
    # In 3.11, the behavior of enum.IntFlag changed
    # https://docs.python.org/3.11/whatsnew/3.11.html
    # We're trying to get a human-readable version
    def enum_intflag_for_json(val: enum.IntEnum):
        if isinstance(name := val.name, str) and len(name):
            retval = name
        else:
            retval = str(val.value)
        return retval
else:
    # Remove the class name
    def enum_intflag_for_json(val: enum.IntFlag):
        return str(val).split('.', 2)[1]


def prep_for_json(val):
    """
    Special cases for conversion to JSON:
    * enum classes
    * bytes-like
    * UUID

    Return the name of an IntEnum, does not help with IntFlag
    So far no IntFlag enums headed to the external API
    """
    # Order is important due to IntEnum and IntFlag behavior (including int)
    if val is None or isinstance(val, (float, str, bool)):
        return val
    elif isinstance(val, enum.IntFlag):
        return enum_intflag_for_json(val)
    elif isinstance(val, enum.IntEnum):
        return val.name
    elif isinstance(val, enum.Enum):
        return val.value
    elif isinstance(val, (bytearray, bytes)):
        return val.hex()
    elif isinstance(val, uuid.UUID):
        return str(val)
    else:
        return val


def data_as_hex(data):
    hex_data = data.hex()
    return ' '.join(b0 + b1 for b0, b1
                    in zip(hex_data[0::2], hex_data[1::2]))


re_data_is_ascii_readable = re.compile('^[\x20-\x7e]*$')
re_data_is_ascii_readable_with_subs = re.compile('^[\r\n\t\x20-\x7e]*$')
tt_rnt_glyphs = str.maketrans("\r\n\t", "\u240d\u240a\u2409")
tt_space_glpyh = str.maketrans(" ", "\u2423")


def data_as_readable(data, replace_rnt=True, replace_space=False):
    """
    Convert a string, bytes, or bytearray object to a "readable" string
    if able to do so, return '' if not readable.

    "readable" is only containing the ASCII characters [space] through ~ (tilde)
    potentially with substitution of glyphs for \r \n \t and/or [space]

    Ref: http://www.unicode.org/charts/PDF/U2400.pdf

    :param data:            str, bytes, or bytearray to be converted
    :param replace_rnt:     Allow \r \n \t and substitute ␍ ␊ ␉
                            (considered not readable otherwise)
    :param replace_space:   Substitute ␣ for [space]
    :return:                str: converted to readable, or ''
    """
    if isinstance(data, (bytes, bytearray)):
        try:
            data = data.decode('ascii')  # enforce one character per byte
        except UnicodeDecodeError:
            return ''
    if not isinstance(data, str):
        raise TypeError("Expected str, bytes, or bytearray")
    out = ""
    if replace_rnt:
        if re_data_is_ascii_readable_with_subs.match(data):
            out = data.translate(tt_rnt_glyphs)
    else:
        if re_data_is_ascii_readable.match(data):
            out = data
    if replace_space:
        out = out.translate(tt_space_glpyh)
    return out


def data_as_readable_or_hex(data, replace_rnt=True, replace_space=False):
    """
    Convert a string, bytes, or bytearray object to a "readable" string
    if able to do so, return data_as_hex(data) if not readable.

    "readable" is only containing the ASCII characters [space] through ~ (tilde)
    potentially with substitution of glyphs for \r \n \t and/or [space]

    Ref: http://www.unicode.org/charts/PDF/U2400.pdf

    :param data:            str, bytes, or bytearray to be converted
    :param replace_rnt:     Allow \r \n \t and substitute ␍ ␊ ␉
                            (considered not readable otherwise)
    :param replace_space:   Substitute ␣ for [space]
    :return:                str: converted to readable, else data_as_hex(data)
    """
    if len(data) == 0:
        return ''
    out = data_as_readable(data, replace_rnt, replace_space)
    if len(out) == 0:
        if not isinstance(data, (bytes, bytearray)):
            # Try to be helpful and assume it is byte-by-byte
            # data_as_readable() has already confirmed str, bytes, bytearray
            data = data.encode('ascii')
        out = data_as_hex(data)
    return out


def timestamp_to_str_with_ms(timestamp: float, show_date=True) -> str:
    string = datetime.fromtimestamp(
        timestamp).isoformat(sep=' ', timespec='milliseconds')
    if not show_date:
        (d, t) = string.split(' ', maxsplit=2)
        string = t
    return string


def call_str(full_trace=True) -> str:
    import inspect
    stack = inspect.stack()[2]
    retval = f"at {stack.function}:{stack.lineno}"
    if full_trace:
        idx = 3
        while True:
            try:
                stack = inspect.stack()[idx]
                next_caller = f"{stack.function}:{stack.lineno}"
                if stack.function.startswith('_run'):
                    break
                retval = f"{retval} < {next_caller}"
            except IndexError:
                break
            idx += 1
    return retval


# As run in a thread-pool executor, need a way to cleanly stop the thread
# so require abandon_on_event

async def mp_event_wait(event: multiprocessing.Event,
                        timeout: Optional[float],
                        abandon_on_event:
                            Union[asyncio.Event,
                                  multiprocessing.Event]) -> bool:
    done = event.is_set()
    end_time = (time.time() + timeout) if timeout else None
    RECHECK_PERIOD = 1.0 # seconds
    while (not done
           and (not end_time
                or (end_time and (now := time.time()) < end_time))
           and (abandon_on_event and not abandon_on_event.is_set())):
        if end_time:
            wait_time = min(end_time - now, RECHECK_PERIOD)
        else:
            wait_time = RECHECK_PERIOD
        task = asyncio.get_running_loop().run_in_executor(
            None, event.wait, wait_time)
        done = await task
    return done


async def mq_queue_get(mp_queue: multiprocessing.Queue,
                       timeout: Optional[float],
                       abandon_on_event:
                       Union[asyncio.Event,
                       multiprocessing.Event]) -> bool:

    end_time = (time.time() + timeout) if timeout else None
    RECHECK_PERIOD = 1.0  # seconds
    done = False
    qexc = None
    data = None
    while (not done
           and (not end_time
                or (end_time and (now := time.time()) < end_time))
           and (abandon_on_event and not abandon_on_event.is_set())):
        if end_time:
            wait_time = min(end_time - now, RECHECK_PERIOD)
        else:
            wait_time = RECHECK_PERIOD
        try:
            task = asyncio.get_running_loop().run_in_executor(
                None, mp_queue.get, True, wait_time)
            data = await task
            done = True  # As otherwise it would have raised queue.Empty
        except queue.Empty as e:
            qexc = e
            done = False
    if qexc:
        raise qexc
    else:
        return data


class EventReadOnly:
    """
    Like an asyncio.Event, but can only wait() and check is_set()
    """
    def __init__(self, backing_event: asyncio.Event):
        self._backing_event = backing_event

    def is_set(self):
        return self._backing_event.is_set()

    async def wait(self):
        return await self._backing_event.wait()
