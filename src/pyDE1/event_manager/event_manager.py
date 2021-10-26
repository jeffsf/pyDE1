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
import multiprocessing
import multiprocessing.connection as mpc
import queue
import time
import uuid
from inspect import iscoroutinefunction, signature
from typing import Optional, Coroutine, Union, List

import pyDE1
from pyDE1.event_manager.payloads import (
    EventNotification, EventNotificationAction, EventNotificationName,
    EventPayload, SequencerGateName, SequencerGateNotification
)
from pyDE1.flow_sequencer import FlowSequencer

logger = pyDE1.getLogger('EventManager')

LOG_DELAYS = False


# Extend asyncio.Event() to notify over the API as well


class EventWithNotify (asyncio.Event):

    def __init__(self, sender, name: EventNotificationName):
        if not isinstance(name, EventNotificationName):
            raise TypeError(
                "EventNotification needs a valid EventNotificationName, not "
                f"'{name}'")
        super(EventWithNotify, self).__init__()
        self._sender = sender
        self._event_name = name

    def set(self):
        super(EventWithNotify, self).set()
        en = EventNotification(
            arrival_time=time.time(),
            sender=self._sender,
            name=self._event_name,
            action=EventNotificationAction.SET
        )
        asyncio.create_task(send_to_outbound_pipes(en))

    def clear(self):
        super(EventWithNotify, self).clear()
        en = EventNotification(
            arrival_time=time.time(),
            sender=self._sender,
            name=self._event_name,
            action=EventNotificationAction.CLEAR
        )
        asyncio.create_task(send_to_outbound_pipes(en))


class SequencerGate (EventWithNotify):
    """
    Extends to add the sequence ID
    """

    def __init__(self, sender, name: SequencerGateName):
        if not isinstance(name, SequencerGateName):
            raise TypeError(
                "EventNotification needs a valid SequencerGateName, not "
                f"'{name}'")
        super(SequencerGate, self).__init__(sender=sender, name=name)

    def set(self):
        # Get to the Event without sending another notification
        super(EventWithNotify, self).set()
        sgn = SequencerGateNotification(
            arrival_time=time.time(),
            sender=self._sender,
            name=self._event_name,
            action=EventNotificationAction.SET
        )
        # Here's where active_state gets set
        self._sender: FlowSequencer
        sgn.active_state = self._sender.active_state
        asyncio.create_task(send_to_outbound_pipes(sgn))

    def clear(self):
        super(EventWithNotify, self).clear()
        sgn = SequencerGateNotification(
            arrival_time=time.time(),
            sender=self._sender,
            name=self._event_name,
            action=EventNotificationAction.CLEAR
        )
        # Here's where active_state gets set
        self._sender: FlowSequencer
        sgn.active_state = self._sender.active_state
        asyncio.create_task(send_to_outbound_pipes(sgn))


async def send_to_outbound_pipes(payload: EventPayload):

    # multiprocessing.queue() can block at least on "full"
    # macOS doesn't support qsize()

    if payload._event_time is None:
        payload._event_time = time.time()
    q_payload = payload.as_json()
    # for pipe in [SubscribedEvent.outbound_pipe,
    #              SubscribedEvent.database_queue]:
    #     if SubscribedEvent.outbound_pipe is not None:
    #         pipe.send(q_payload)
    SubscribedEvent.outbound_pipe.send(q_payload)
    # Will raise queue.Full
    try:
        SubscribedEvent.database_queue.put_nowait(q_payload)
    except queue.Full:
        logger.error("Database queue full")
        # Not much else to do. Killing a shot in progress seems excessive


class SubscribedEvent:
    """
    A canonical pub/sub system for EventPayload objects under asyncio

    This is intended to be a singleton for each event type
    and with a single publisher.

    If outbound_pipe: is not None
    and EventPayload._internal_only is False (default)
    the EventPayload.as_json() will be delivered to that queue.

    SubscribedEvent.outbound_pipe and EventPayload._internal_only
    are class properties at this time.

    """

    outbound_pipe: Optional[mpc.Connection] = None
    database_queue: Optional[multiprocessing.Queue] = None

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
              (Or not, as it isn't exposed as a writable object through an API)
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

                await s[1](payload)
        internal_done = time.time()

        # multiprocessing.queue() can block at least on "full"
        # macOS doesn't support qsize()
        if not payload._internal_only:
            await send_to_outbound_pipes(payload)

        delivery_done = time.time()

        if LOG_DELAYS and not payload._internal_only:
            logger.info(
                "JSON and queueing time: "
                f"{(delivery_done - internal_done) * 1000:0.3f} ms")

        if (interpacket := payload.create_time - self._last_create_time) < 0:
            logger.error(
                "Out-of-sequence payload delivery by "
                f"{-interpacket * 1000:0.3f} ms")
        if LOG_DELAYS:
            delay = (delivery_done - payload.create_time) * 1000
            logger.debug( f"Dispatch delay: {delay:.3f} ms {type(payload)}")
        return tasks
