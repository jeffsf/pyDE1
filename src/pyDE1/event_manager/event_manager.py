"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Initial thoughts on EventManager

Should be able to dispatch quickly, so probably should create tasks
and add them to the loop

A subscriber should be able to remove itself. This supports one-shot
as well as being able to do coarse-grained, state-based filtering.
"Only send me updates if recording a shot." Need some kind of handle
on the subscription. Return a uuid.uuid4() ?

The event_data should always contain:
  arrival_time -- the time at which the "triggering action" occurred
  event_time -- the time that the event was told to dispatch
  sender -- the high-level object that generated the event,
            de1, scale, scale_processor, BLE changes, API, ...
  data -- an object containing data associated with the event, can be None

The list of available events should be discoverable, along with a description
of what they are. Is there a way to get all the defined subclasses of a class?
pyDE1.de1.c_api.PackedAttr.__subclasses__()

There should be a queue, in case things back up
Entries in the queue should be tagged with insertion time as event_time
This can then be compared with delivery time, as well as by a consumer

A queue with a single worker will suggest, but not guarantee, ordered delivery

One queue per event type seems a good start, though, for example,
"on every state change" might be processed before or after "on flow change"
One way to resolve this is to only notify once for anything.
(Yes, potentially use flags for the DE1 state info, major, minor,
flow state enter, flow state leave, flow phase change)

Use a mask to filter? Maybe later -- state changes, but what else?

What happens if the worker dies? How does this get detected?
Watchdog? Check on every add?

Don't need a queue to start as there will only be one publisher for an event.
"""
import asyncio
import json
import logging
import time
import uuid

from copy import copy
from inspect import iscoroutine, iscoroutinefunction, signature
from typing import Optional, Coroutine, Union, List

import pyDE1.default_logger

logger = logging.getLogger('EventManager')

# TODO: Need loggable representation of payloads

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

    def __init__(self,
                 arrival_time: float,
                 create_time: Optional[float] = None,
                 data: Optional[None] = None):
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
        work = {k: v for k, v in self.__dict__.items()
                if not k.startswith('_')}
        for key in ('version', 'event_time'):
            try:
                work[key] = self.__dict__['_' + key]
            except KeyError:
                work[key] = None
        work['sender'] = type(self._sender).__name__
        work['class'] = type(self).__name__

        return json.dumps(work)


class SubscribedEvent:
    """
    A canonical pub/sub system for EventPayload objects under asyncio

    This is intended to be a singleton for each event type
    and with a single publisher. There is no queue nor lock.
    """

    def __init__(self, sender):
        self._sender = sender
        self._subscribers = []
        # perhaps don't need a lock on the list as not threaded
        self._subscriber_list_lock = asyncio.Lock()
        self._last_create_time = 0

    async def subscribe(self,
                        callback: Coroutine[
                            None, EventPayload, None]) -> uuid.UUID:
        """
        Subscribe to the series of events

        Returns a UUID that can be later used to unsubscribe
        """
        # iscoroutine() fails on "async def something(payload)
        if not iscoroutinefunction(callback):
            raise TypeError(
                f"The callback must be a coroutine function: {callback}")

        # For now, just assume that optional parameters aren't being used
        scb = signature(callback)
        if len(scb.parameters) != 1:
            raise TypeError(
                f"The callback must accept a single argument: {scb.parameters}")

        id = uuid.uuid4()
        async with self._subscriber_list_lock:
            self._subscribers.append((id, callback))
        logger.debug(f"Subscribed {callback} to {self}")
        return id

    async def unsubscribe(self, id: Union[uuid.UUID, str,
                                          None]) -> Union[bool, None]:
        """
        Unsubscribe from an event
        Returns True on success, None if not found, and False on failure
        (presently that the id isn't a valid UUID')

        If None is the id, it returns True
        (allows for removal of placeholders that haven't been subscribed)
        """
        if id is None:
            return True
        retval = None
        if isinstance(id, str):
            try:
                id = uuid.UUID(id)
            except ValueError:
                return False
        async with self._subscriber_list_lock:
            len_before = len(self._subscribers)
            self._subscribers = list(
                filter(lambda s: s[0] != id, self._subscribers))
            len_after = len(self._subscribers)
        if len_after < len_before:
            retval = True
        else:
            retval = None
        return retval

    async def publish(self, payload: EventPayload) -> List[asyncio.Task]:
        """
        Take an EventPayload and distribute to all subscribers

        Returns a list of tasks created

        TODO: Consider if a deepcopy of the EventPayload is justified
              (It probably is, as it gets passed by reference)
        """
        payload._sender = self._sender
        async with self._subscriber_list_lock:
            payload._event_time = time.time()
            tasks = []
            for s in self._subscribers:
                # These have ben validated as coroutines
                # with single arguments on subscribe()
                #
                # # TODO: The copy() isn't being done asynchronously
                #
                # # TODO: Check this with the profiler
                # #       Might be better to off the whole thing
                # #       await/gather is scary if one hangs
                #
                # t = asyncio.create_task(s[1](copy(payload)))
                # tasks.append(t)
                # await s[1](copy(payload))

                # TODO: Figure out if/how to protect payload
                #       from unintentional damage from others

                await s[1](payload)
        now = time.time()

        if (interpacket := payload.create_time - self._last_create_time) < 0:
            logger.error(
                "Out-of-sequence payload delivery by "
                f"{-interpacket * 1000:0.3f} ms")
        delay = (now - payload.create_time) * 1000
        logger.debug( f"Dispatch delay: {delay:.3f} ms {type(payload)}")
        return tasks
