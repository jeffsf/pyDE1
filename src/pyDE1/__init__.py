"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Provides pyDE1.getLogger()

"""
import logging
from typing import Optional

_ROOT_LOGGER_NAME = 'pyDE1'
_ROOT_LOGGER_PREFIX = _ROOT_LOGGER_NAME + '.'
_ROOT_LOGGER_PREFIX_LEN = len(_ROOT_LOGGER_PREFIX)


def getLogger(name: Optional[str]=None) -> logging.Logger:
    pyde1_root = logging.getLogger(_ROOT_LOGGER_NAME)
    retval = None
    if name is None:
        retval = pyde1_root
    elif name == 'root':
        retval = logging.getLogger()
    elif name.startswith('root.'):
        retval = logging.getLogger(name[5:])
    else:
        retval = pyde1_root.getChild(name)
    return retval