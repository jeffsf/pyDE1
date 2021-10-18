import enum
import json
import time
import uuid
from typing import Optional

import pyDE1
from pyDE1.utils import prep_for_json

logger = pyDE1.getLogger('EventManager.Payloads')

class EventPayload:
    """
    A canonical event payload, passed to Event.publish()
    and received by each of the subscribers as their argument.

    Additional attributes can be added by subclasses to pass data

    arrival_time    is mandatory, represents when the "trigger" occurred
    create_time     if None, will use time.time()
    _sender         will be filled out by the Event.publish() method
    _event_time     will be filled out by the Event.publish() method
    """
    _internal_only = False

    def __init__(self,
                 arrival_time: float,
                 create_time: Optional[float] = None,
                 ):
        self._version = None
        self._sender = None
        self.arrival_time = arrival_time
        if create_time is None:
            create_time = time.time()
        self.create_time = create_time
        self._event_time = None

    @property
    def version(self):
        return self._version

    @property
    def sender(self):
        return self._sender

    @property
    def event_time(self):
        return self._event_time

    # Keep signature consistent with PackedAttr.as_wire_bytes()
    def as_json(self):
        """
        Convert to JSON for external consumers.
        Consumer is responsible for "wrapping" this payload for delivery.

        The sender is converted to the name of the sender's class.
        __name__ should return the base name, though would return,
        for example "AtomaxSkaleII" and not "Scale"
        Times are in time.time() format, 1623096954.5960422

        Only _name, _version, _sender and _event_time
        are accepted from "private" attributes.
        They are translated to 'name', 'version', 'sender' and 'event_time'
        """
        # IntEnum gets JSON-ified as an int
        work = {k: prep_for_json(v) for k, v in self.__dict__.items()
                if not k.startswith('_')}
        for key in ('version', 'event_time'):
            try:
                work[key] = self.__dict__['_' + key]
            except KeyError:
                work[key] = None
        work['sender'] = type(self._sender).__name__
        work['class'] = type(self).__name__

        return json.dumps(work)


class EventNotificationName (enum.Enum):
    """
    As "subclassing an enumeration is allowed only
        if the enumeration does not define any members."
    all need to be defined here
    """
    pass


class EventNotificationAction (enum.Enum):
    SET = 'set'
    CLEAR = 'clear'


class EventNotification (EventPayload):

    def __init__(self, arrival_time: Optional[float],
                 create_time: Optional[float] = None,
                 sender = None,
                 name: EventNotificationName = None,
                 action: EventNotificationAction = None
                 ):
        if not isinstance(name, EventNotificationName):
            raise TypeError(
                "EventNotification needs a valid EventNotificationName, not "
                f"'{name}'")
        if not isinstance(action, EventNotificationAction):
            raise TypeError(
                "EventNotification needs a valid EventNotificationAction, not "
                f"'{action}'")
        if arrival_time is None:
            arrival_time = time.time()
        super(EventNotification, self).__init__(
            arrival_time=arrival_time,
            create_time=create_time,
        )
        self._version = "1.0.0"
        self._sender = sender
        self.name = name.value
        self.action = action.value


class SequencerGateName (EventNotificationName):
    GATE_SEQUENCE_START = "sequence_start"
    GATE_FLOW_BEGIN = "sequence_flow_begin"
    GATE_EXPECT_DROPS = "sequence_expect_drops"
    GATE_EXIT_PREINFUSE = "sequence_exit_preinfuse"
    GATE_FLOW_END = "sequence_flow_end"
    GATE_FLOW_STATE_EXIT = "sequence_flow_state_exit"
    GATE_LAST_DROPS = "sequence_last_drops"
    GATE_SEQUENCE_COMPLETE = "sequence_complete"


class SequencerGateNotification (EventNotification):

    sequence_id = uuid.uuid4()

    @classmethod
    def new_sequence(cls):
        cls.sequence_id = str(uuid.uuid4())
        return cls.sequence_id

    def __init__(self, arrival_time: Optional[float],
                 create_time: Optional[float] = None,
                 sender = None,
                 name: EventNotificationName = None,
                 action: EventNotificationAction = None
                 ):
        super(SequencerGateNotification, self).__init__(
            arrival_time=arrival_time,
            create_time=create_time,
            sender=sender,
            name=name,
            action=action
        )
        self._version = "1.1.0"
        self.sequence_id = self.__class__.sequence_id
        # active_state gets set by the SequencerGate which has a reference
        # to the FlowSequencerImpl, which implements FlowSequencer
        # Otherwise there's a messy circular import
        self.active_state = None    # Gets set