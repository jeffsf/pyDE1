"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import logging
import os
import re
import time

format_string = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logfile_directory = '_logs'

logging.basicConfig(level=logging.DEBUG,
                    format=format_string,
                    )

# It looks like steerr handler comes with "basicConfig"
#     root.handlers = [<StreamHandler <stderr> (NOTSET)>]

# Define console logging
# console = logging.StreamHandler()
# console.setLevel(logging.DEBUG)
# formatter = logging.Formatter(format_string)
# console.setFormatter(formatter)

# Add console logging to root logger
# logging.getLogger('').addHandler(console)

# Trim down the "noise" from asyncio and bleak.backends.bluezdbus.client
logging.getLogger('asyncio').setLevel(logging.INFO)
logging.getLogger('bleak').setLevel(logging.INFO)

logger = logging.getLogger('Logger')

lf_name = time.strftime('default.%Y-%m-%d_%H%M%S.log', time.localtime())
lf_name = os.path.join(logfile_directory, lf_name)
if not os.path.exists(logfile_directory):
    logger.error(
        "logfile_directory '{}' does not exist. Creating.".format(
            os.path.realpath(logfile_directory)
        )
    )
    os.mkdir(logfile_directory)
try:
    lf = logging.FileHandler(lf_name)
except FileNotFoundError:
    logger.critical(
        f"Unable to open {os.path.realpath(lf_name)}"
    )
    raise
lf.setFormatter(logging.Formatter(format_string))
lf.setLevel(logging.DEBUG)
logging.getLogger('').addHandler(lf)
logger.info(f"Logging PID {os.getpid()} to {os.path.realpath(lf_name)}")

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
        data = data.decode('ascii')  # enforce one character per byte
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