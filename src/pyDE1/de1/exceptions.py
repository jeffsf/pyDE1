"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
from http import HTTPStatus


class DE1Error (RuntimeError):
    def __init__(self, *args, **kwargs):
        super(DE1Error, self).__init__(args, kwargs)


class DE1ValueError (DE1Error, ValueError):
    def __init__(self, *args, **kwargs):
        super(DE1ValueError, self).__init__(args, kwargs)


class DE1TypeError (DE1Error, TypeError):
    def __init__(self, *args, **kwargs):
        super(DE1TypeError, self).__init__(args, kwargs)


class DE1AttributeError(DE1Error, AttributeError):
    def __init__(self, *args, **kwargs):
        super(DE1AttributeError, self).__init__(args, kwargs)


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


class DE1OperationInProgressError(DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1OperationInProgressError, self).__init__(args, kwargs)


class DE1APIError (DE1Error):
    def __init__(self, *args, **kwargs):
        super(DE1APIError, self).__init__(*args, **kwargs)


class DE1APITypeError (TypeError, DE1APIError):
    def __init__(self, *args, **kwargs):
        super(DE1APITypeError, self).__init__(*args, **kwargs)


class DE1APIValueError (ValueError, DE1APIError):
    def __init__(self, *args, **kwargs):
        super(DE1APIValueError, self).__init__(*args, **kwargs)


class DE1APIUnsupportedStateTransitionError (DE1APIValueError):
    def __init__(self, target_state, current_state, *args, **kwargs):
        message = "I'm afraid I can't do that Dave." \
                  f" Can't move to {target_state} from {current_state}"
        super(DE1APIUnsupportedStateTransitionError, self).__init__(
            message, *args, **kwargs)


class DE1APIAttributeError (AttributeError, DE1APIError):
    def __init__(self, *args, **kwargs):
        super(DE1APIAttributeError, self).__init__(*args, **kwargs)


class DE1APIKeyError(AttributeError, DE1APIError):
    def __init__(self, *args, **kwargs):
        super(DE1APIKeyError, self).__init__(*args, **kwargs)


class DE1APITooManyFramesError (DE1APIValueError):
    def __init__(self, *args, **kwargs):
        super(DE1APITooManyFramesError, self).__init__(*args, **kwargs)


class MMRTypeError (DE1APITypeError):
    def __init__(self, *args, **kwargs):
        super(MMRTypeError, self).__init__(*args, **kwargs)


class MMRValueError (DE1APIValueError):
    def __init__(self, *args, **kwargs):
        super(MMRValueError, self).__init__(*args, **kwargs)


class MMRDataTooLongError (MMRValueError):
    def __init__(self, *args, **kwargs):
        super(MMRDataTooLongError, self).__init__(*args, **kwargs)


class MMRAddressError (MMRValueError):
    def __init__(self, *args, **kwargs):
        super(MMRAddressError, self).__init__(*args, **kwargs)


class MMRAddressRangeError (MMRAddressError):
    def __init__(self, *args, **kwargs):
        super(MMRAddressRangeError, self).__init__(*args, **kwargs)


class MMRAddressOffsetError (MMRAddressError):
    def __init__(self, *args, **kwargs):
        super(MMRAddressOffsetError, self).__init__(*args, **kwargs)