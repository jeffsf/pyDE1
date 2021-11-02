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
import uuid

from datetime import datetime

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
        # Remove the class name
        return str(val).split('.',2)[1]
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


