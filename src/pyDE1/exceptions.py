"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""


class DE1Error (RuntimeError):
    pass


class DE1ValueError (DE1Error, ValueError):
    pass


class DE1TypeError (DE1Error, TypeError):
    pass


class DE1AttributeError(DE1Error, AttributeError):
    pass


class DE1NoAddressError (DE1Error):
    pass


class DE1NotConnectedError (DE1Error):
    pass


class DE1IsConnectedError (DE1Error):
    """
    Such as trying to wipe state while connected
    """
    pass


class DE1NoHandlerError(DE1Error):
    pass


class DE1ErrorStateReported(DE1Error):
    pass


class DE1OperationInProgressError(DE1Error):
    pass


class DE1APIError (DE1Error):
    pass


class DE1APITypeError (DE1APIError, TypeError):
    pass


class DE1APIValueError (DE1APIError, ValueError):
    def __init__(self, *args, **kwargs):
        super(DE1APIValueError, self).__init__(*args, **kwargs)


class DE1APIUnsupportedFeatureError (DE1APIValueError):
    pass


# Pickle of custom exceptions discussed at
# https://stackoverflow.com/questions/16244923/how-to-make-a-custom-exception-class-with-multiple-init-args-pickleable

class DE1APIUnsupportedStateTransitionError (DE1APIValueError):
    def __init__(self, target_mode, current_state, current_substate,
                 *args, **kwargs):
        # Formatting the message for the super call still fails un-pickle
        try:
            current_state = current_state.name
        except AttributeError:
            pass
        try:
            current_substate = current_substate.name
        except AttributeError:
            pass
        self.target_mode = target_mode
        self.current_state = current_state
        self.current_substate = current_substate
        super(DE1APIUnsupportedStateTransitionError, self).__init__(
            "I'm afraid I can't do that Dave. Can't move to "
            f"{target_mode} from {current_state}, {current_substate}",
            *args, **kwargs)

    def __reduce__(self):
        return (DE1APIUnsupportedStateTransitionError, (self.target_mode,
                                                        self.current_state,
                                                        self.current_substate))


class DE1APIAttributeError (DE1APIError, AttributeError):
    pass


class DE1APIKeyError(DE1APIError, KeyError):
    pass


class DE1APITooManyFramesError (DE1APIValueError):
    pass


class MMRTypeError (DE1APITypeError):
    pass


class MMRValueError (DE1APIValueError):
    pass


class MMRDataTooLongError (MMRValueError):
    pass


class MMRAddressError (MMRValueError):
    pass


class MMRAddressRangeError (MMRAddressError):
    pass


class MMRAddressOffsetError (MMRAddressError):
    pass


class DE1DBError (RuntimeError):
    pass

class DE1IncompleteSequenceRecordError (DE1DBError):
    pass

class DE1DBNoMatchingRecord (DE1DBError):
    pass

class DE1DBConsistencyError (DE1DBError):
    pass