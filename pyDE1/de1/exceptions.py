"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

class DE1Error (RuntimeError):
    def __init__(self, *args, **kwargs):
        super(DE1Error, self).__init__(args, kwargs)

class DE1ValueError (DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1ValueError, self).__init__(args, kwargs)

class DE1NoAddressError (DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1NoAddressError, self).__init__(args, kwargs)


class DE1NotConnectedError (DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1NotConnectedError, self).__init__(args, kwargs)


class DE1NoHandlerError(DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1NoHandlerError, self).__init__(args, kwargs)


class DE1ErrorStateReported(DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1ErrorStateReported, self).__init__(args, kwargs)