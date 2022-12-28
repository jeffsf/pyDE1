"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import enum
import logging
import time
import warnings

from typing import (
    Optional, Union, NamedTuple, Callable, Type, TypedDict, Literal
)

import bleak
import bleak.exc
from bleak import BleakClient
from bleak.backends.device import BLEDevice

from pyDE1.exceptions import DE1NoAddressError
from pyDE1.utils import EventReadOnly

try:
    from pyDE1.utils import call_str
except ImportError:
    def call_str(*args, **kwargs) -> str:
        return '(call_str not implemented)'

try:
    from bleak.backends.bluezdbus.scanner import BlueZScannerArgs
except ImportError:
    pass
try:
    from bleak.backends.winrt.client import WinRTClientArgs
except ImportError:
    class WinRTClientArgs(TypedDict, total=False):
        address_type: Literal["public", "random"]
        use_cached_services: bool
#
#   File "[...]]/bleak/backends/winrt/client.py", line 22, in <module>
#     from bleak_winrt.windows.devices.bluetooth import (
# ModuleNotFoundError: No module named 'bleak_winrt'

from pyDE1.lock_logger import LockLogger

IN_PROGRESS_HOLDOFF = 0.2 # seconds, works, 0.1 seemed too short

class CaptureRequest (enum.Enum):
    CAPTURE = 'C'
    RELEASE = 'R'
    CANCEL  = 'X'


class CaptureQueue (NamedTuple):
    connected:  Optional[CaptureRequest]
    pending:    Optional[CaptureRequest]
    target:     Optional[CaptureRequest]

    def __str__(self):
        try:
            retval =  '{}({}, {}, {})'.format(
                self.__class__.__name__,
                self.connected.name if self.connected else None,
                self.pending.name if self.pending else None,
                self.target.name if self.target else None,
            )
        except AttributeError:
            retval = repr(self)

        return retval


def cq_from_code(code: str) -> CaptureQueue:
    tt = {
        'C': CaptureRequest.CAPTURE,
        'R': CaptureRequest.RELEASE,
        'X': CaptureRequest.CANCEL,
        'N': None,
    }
    return CaptureQueue(
        connected=tt[code[0].upper()],
        pending=tt[code[1].upper()],
        target=tt[code[2].upper()],
    )


def cq_to_code(cq: CaptureQueue) -> str:
    retval = ''
    for attr in ('connected', 'pending', 'target'):
        try:
            c = getattr(cq, attr).value
        except AttributeError:
            c = 'N'
        retval += c
    return retval


def task_for_log(t: asyncio.Task) -> str:
    try:
        name = t.get_name()
        state = 'Running'
        if t.cancelled():
            state = 'Cancelled'
        elif t.done():
            state = 'Done'
        retval = f"<Task '{name}', {state}, {t.get_coro().cr_code.co_name}()>"
    except Exception:
        retval = str(t)
    return retval


class ManagedBleakClient (BleakClient):
    """
    Implements BleakClient

    Requires bleak 0.18.1 or later which introduced
    concrete BleakClient and self._backend
    """

    def __init__(self,
                 address_or_ble_device: Optional[Union[BLEDevice, str]],
                 disconnected_callback: Optional[
                     Callable[[BleakClient], None]] = None,
                 *,
                 timeout: float = 10.0,
                 winrt: Optional[WinRTClientArgs] = None,
                 backend: Optional[Type[BleakClient]] = None,
                 on_change_callback: Optional[
                     Callable[['ManagedBleakClient',
                               CaptureQueue,
                               CaptureQueue], None]] = None,
                 logger: Optional[logging.Logger] = None,
                 **kwargs,
                 ):

        if backend is not None:
            raise ValueError(
                f"{self.__class__.__name__} manages its own backends "
                f"through replacement, omit backend= from init call")

        if winrt is None:
            winrt = {}

        # Assigning logger needs to be ahead of generate_disconnected_callback
        if logger is None:
            logger = logging.getLogger(self.__class__.__name__)
            logger.warning(f"Using fall-back logger {logger}")
        self.logger = logger

        self._legacy_disconnected_callback = disconnected_callback
        self._on_change_callback = on_change_callback

        # Retain init params for potentially replacing backend
        self._init_winrt = winrt
        self._init_kwargs = kwargs

        self._change_address_lock = asyncio.Lock()

        if address_or_ble_device is None:
            address_or_ble_device = ''

        # NB: Replicate any changes here in change_address()
        super(ManagedBleakClient, self).__init__(
                address_or_ble_device=address_or_ble_device,
                disconnected_callback=self._generate_disconnected_callback(),
                timeout=timeout,
                winrt=winrt,
                backend=backend,
                **kwargs,
        )

        self._capture_queue_lock = asyncio.Lock()
        self.__capture_queue: CaptureQueue = CaptureQueue(None, None, None)

        self._event_captured = asyncio.Event()
        self._event_released = asyncio.Event()
        self._event_no_pending = asyncio.Event()
        self._event_connected = asyncio.Event()
        self._event_disconnected = asyncio.Event()

        # Cache wrapped versions
        self._event_captured_ro = EventReadOnly(self._event_captured)
        self._event_released_ro = EventReadOnly(self._event_released)
        self._event_no_pending_ro = EventReadOnly(self._event_no_pending)
        self._event_connected_ro = EventReadOnly(self._event_connected)
        self._event_disconnected_ro = EventReadOnly(self._event_disconnected)


        self._retry_wait_event = asyncio.Event()
        self._retry_wait_task: Optional[asyncio.Task] = None
        # Using an event allow retries to resume immediately
        # without fancy scheduling and rescheduling
        self._retry_since = None
        #
        self._retry_start_initial_delay = 300 # seconds
        self._retry_initial_delay = 15 # seconds
        self._retry_start_long_delay = 1800  # seconds
        self._retry_long_delay = 60 # seconds

        self._pending_task: Optional[asyncio.Task] = None

        self._capture_release_done_callback = \
            self._generate_capture_release_done_callback()

        self._reset_all_unsafe()

    ###
    ### Public API
    ###

    async def change_address(
            self, new_addr: Optional[Union[BLEDevice, str]] = None) -> bool:
        """
        If address is the same, returns immediately
        If the address is different, will
          * Disconnect existing client
          * Create a new backend with the parameters saved from __init__()
            but with the new address and save the new address

        If None or the empty string is passed, disconnects and "forgets" address

        NB: Other actions aren't explicitly locked out during an address change

        :returns    bool    True if the address has been changed
        """
        if new_addr is None:
            new_addr = ''

        if isinstance(new_addr, BLEDevice):
            check_addr = new_addr.address
        else:
            check_addr = new_addr
        if check_addr == self.address:
            self.logger.info(
                f"change_address({check_addr}) would not change address. "
                "No action taken.")
            return False

        ll = LockLogger(self._change_address_lock, 'ChangeAddress').check()
        async with self._change_address_lock:
            ll.acquired()
            # NB: Other actions aren't explicitly locked out
            # NB: Go directly to _queue_request as release or request_release
            #     would try to acquire _change_address_lock and hang
            await self._queue_request(CaptureRequest.RELEASE)
            await self.event_released.wait()

            # NB: This makes some assumptions about bleak internals
            current_disconnected_callback = self._backend._disconnected_callback
            current_timeout = self._backend._timeout

            new_bleak_client = BleakClient(
                address_or_ble_device=check_addr,
                disconnected_callback=current_disconnected_callback,
                timeout=current_timeout,
                winrt=self._init_winrt,
                backend=None,
                **self._init_kwargs,
            )
            self._backend = new_bleak_client._backend
            self._reset_all_unsafe()

        ll.released()
        return True

    async def connect(self, **kwargs) -> bool:
        """
        Intercept connect and replace with "capture()"

        super:
            Connect to the specified GATT server.

            Args:
                **kwargs: For backwards compatibility - should not be used.

            Returns:
                Always returns ``True`` for backwards compatibility.
        """
        self.logger.warning(
            f"Prefer {self.__class__.__name__}.capture() to .connect()"
        )
        await self.capture()
        return True

    async def disconnect(self) -> bool:
        """
        Intercept disconnect and replace with "release()"

        super:

            Disconnect from the specified GATT server.

            Returns:
                Always returns ``True`` for backwards compatibility.
        """
        self.logger.warning(
            f"Prefer {self.__class__.__name__}.release() to .disconnect()"
        )
        await self.release()
        return True

    async def capture(self, timeout: Optional[float] = None) -> bool:
        """
        Request capture and wait up to timeout
        Default is self._backend._timeout

        :return: is_captured
        """
        await self.request_capture()
        if timeout is None:
            timeout = self._backend._timeout
        await asyncio.wait_for(self.event_captured.wait(), timeout=timeout)
        return self.is_captured

    async def release(self, timeout: Optional[float] = None) -> bool:
        """
        Request capture and wait up to timeout
        Default is self._backend._timeout

        :return: is_released
        """
        await self.request_release()
        await asyncio.wait_for(self.event_released.wait(), timeout=timeout)
        return self.is_released

    async def request_capture(self):
        """
        Request capture and "immediately" return
        """
        if not self.address:
            raise DE1NoAddressError(f"{self}.address: '{self.address}'")
        ll = LockLogger(self._change_address_lock, "ChangeAddress").check()
        async with self._change_address_lock:
            ll.acquired()
            await self._queue_request(CaptureRequest.CAPTURE)
        ll.released()

    async def request_release(self):
        """
        Request release and "immediately" return
        """
        ll = LockLogger(self._change_address_lock, "ChangeAddress").check()
        async with self._change_address_lock:
            ll.acquired()
            await self._queue_request(CaptureRequest.RELEASE)
        ll.released()

    @property
    def event_captured(self) -> EventReadOnly:
        """
        Returns an asyncio.Event that is set when the device is captured
        """
        return self._event_captured_ro

    @property
    def event_released(self) -> EventReadOnly:
        """
        Returns an asyncio.Event that is set when the device is released
        """
        return self._event_released_ro

    @property
    def event_no_pending(self) -> EventReadOnly:
        """
        Returns an asyncio.Event that is set when there are no pending tasks
        on the capture/release queue
        """
        return self._event_no_pending_ro

    @property
    def event_connected(self) -> EventReadOnly:
        """
        Returns an asyncio.Event that is set when there are no pending tasks
        on the capture/release queue
        """
        return self._event_connected_ro

    @property
    def event_disconnected(self) -> EventReadOnly:
        """
        Returns an asyncio.Event that is set when there are no pending tasks
        on the capture/release queue
        """
        return self._event_disconnected_ro

    # Supplied by superclass
    # @property
    # def is_connected(self) -> self._DeprecatedIsConnectedReturn:
    # (not bool)

    @property
    def is_captured(self) -> bool:
        return self._event_captured.is_set()

    @property
    def is_released(self) -> bool:
        return self._event_released.is_set()

    @property
    def connectivity_task_pending(self) -> bool:
        """
        At least at this time, is_captured and is_released
        are "at the moment", even if there is a task running
        that may change the connectivity.
        """
        return self._capture_queue.pending is not None

    @property
    def active_request(self) -> Optional[CaptureRequest]:
        """
        Returns the current target/goal for capture/release
        """
        return self._capture_queue.target

    @property
    def on_change_callback(self):
        return self._on_change_callback
    
    @on_change_callback.setter
    def on_change_callback(self, val: Callable):
        """
        Callback is called any time the capture queue changes with
        (mbc: ManagedBleakClient, old: CaptureQueue, new: CaptureQueue)
        """
        self._on_change_callback = val

    def set_disconnected_callback(
        self, callback: Optional[Callable[[BleakClient], None]], **kwargs
    ) -> None:
        """Set the disconnect callback.

        .. deprecated:: 0.17.0
            This method will be removed in a future version of Bleak.
            Pass the callback to the :class:`BleakClient` constructor instead.

        Args:
            callback: callback to be called on disconnection.

        """
        warnings.warn(
            "This method will be removed future version, pass the callback "
            f"to the {self.__class__.__name__} constructor instead.",
            FutureWarning,
            stacklevel=2,
        )
        self._legacy_disconnected_callback = callback


    ###
    ### End of public API
    ###

    def _reset_all_unsafe(self):
        # self.logger.info(f'_reset_all_unsafe()')
        self.logger.debug(f'_reset_all_unsafe() {call_str()}')
        self._event_captured.clear()
        self._event_released.clear()
        self._event_no_pending.set()
        self._event_disconnected.clear()
        self._event_connected.clear()
        self._retry_reset()
        if self._pending_task is not None:
            self._pending_task.cancel()
            # NB: It may still come back to haunt
        # Note accessing double-underscore version
        # and then calling the on-change method
        self.__capture_queue = CaptureQueue(None, None, None)
        if self._on_change_callback is not None:
            self._on_change_callback(self,
                                     self._capture_queue,
                                     self._capture_queue)

    @property
    def _capture_queue(self):
        return self.__capture_queue

    @_capture_queue.setter
    def _capture_queue(self, new_cq: CaptureQueue):
        old_cq = self.__capture_queue
        self.__capture_queue = new_cq
        if new_cq != old_cq and self._on_change_callback is not None:
            logger = self.logger.getChild('CQ')
            logger.debug(
                'Calling {} with {} => {}'.format(
                    self._on_change_callback.__name__,
                    cq_to_code(old_cq),
                    cq_to_code(new_cq)
                ))
            self._on_change_callback(self, old_cq, new_cq)


    async def _queue_request(self, request: CaptureRequest) -> bool:
        if request not in (CaptureRequest.CAPTURE,
                           CaptureRequest.RELEASE):
            raise ValueError(
                "Request must be CaptureState.CAPTURE or .RELEASE, "
                f"not {request}")
        ll = LockLogger(self._capture_queue_lock, 'CaptureQueue').check()
        async with self._capture_queue_lock:
            ll.acquired()
            retval = self._maybe_initiate_action_have_lock(request=request)
        ll.released()
        return retval

    def _maybe_initiate_action_have_lock(self,
                            request: Optional[CaptureRequest] = None) -> bool:
        """
        Given the current _capture_queue, evaluate the target, current,
        and pending. If needed, initiate a new task or cancel the pending.
        Update _capture_queue

        If request is None, use the existing target

        Returns True if an action was taken

        NB: Only call while holding _capture_queue_lock
        """
        assert self._capture_queue_lock.locked(), \
                f"{self}._capture_queue_lock was not locked "

        logger = self.logger.getChild('Initiate')

        next_cq_action = None
        new_action_taken = False

        cq = self._capture_queue
        if request is None:
            request = cq.target

        if request is None:
            logger.warning(
                f"No request, no change from {self._capture_queue}")
            return False

        if cq.connected == request:

            if cq.pending is None:
                next_cq_action = None

            else:
                next_cq_action = CaptureRequest.CANCEL

        else:  # cq.current != request

            if cq.pending is None:
                next_cq_action = request

            elif cq.pending == request:
                next_cq_action = request

            else:
                next_cq_action = CaptureRequest.CANCEL

        if cq.pending != next_cq_action:
            self._start_request_with_lock(next_cq_action)
            new_action_taken = True

        self._capture_queue = CaptureQueue(
            connected=cq.connected,
            pending=next_cq_action,
            target=request,
        )

        if next_cq_action== CaptureRequest.CAPTURE:
            if not self._retry_is_active:
                self._retry_start()
            else:
                pass
            self._retry_set_timer()
        else:
            self._retry_reset()

        return new_action_taken

    def _start_request_with_lock(self, req: CaptureRequest):
        if req == CaptureRequest.CAPTURE:
            self._start_capture_with_lock()
        elif req == CaptureRequest.RELEASE:
            self._start_release_with_lock()
        elif req == CaptureRequest.CANCEL:
            self._start_cancel_with_lock()
        else:
            raise ValueError(f"Unrecognized request: {req}")

    def _start_capture_with_lock(self):
        # TODO: build this out
        self.logger.debug("Start capture")
        self._retry_set_timer()
        t = asyncio.create_task(self._backend_connect_after_retry_wait_event())
        self._pending_task = t
        t.add_done_callback(self._capture_release_done_callback)
        self.logger.debug(f"task: {task_for_log(t)}")
        return t

    def _start_release_with_lock(self):
        self.logger.info("Start release")
        t = asyncio.create_task(self._backend.disconnect())
        self._pending_task = t
        t.add_done_callback(self._capture_release_done_callback)
        self.logger.debug(f"task: {task_for_log(t)}")
        return t

    def _start_cancel_with_lock(self):
        self.logger.info("Start cancel")
        if (pt := self._pending_task) is not None:
            self.logger.debug(f"Cancel request: {task_for_log(pt)}")
            pt.cancel()
        else:
            self.logger.warning('No pending task to cancel')

    # Retry approach:
    # Only for connect/capture
    # Use _retry_wait_event so that it can be immediately released
    # if it is requested again

    async def _backend_connect_after_retry_wait_event(self):
        # TODO: This should be cleaner on timeout
        await self._retry_wait_event.wait()
        # NB: Not clearing here has the advantage for testing
        #     that the event is always set after _backend.connect()
        # self._retry_wait_event.clear()
        try:
            await self._backend.connect()
        except asyncio.CancelledError:
            self.logger.info("connect retry CancelledError caught, pass")
            pass
        except asyncio.TimeoutError:
            self.logger.info("connect retry TimeoutError caught, pass")
            pass
        except bleak.exc.BleakDeviceNotFoundError as e:
            # bleak 0.19.0 and later
            e: bleak.exc.BleakDeviceNotFoundError
            self.logger.info(f"Seemingly stale device, resetting: {e}")
            self._backend._device_path = None
            await self._backend_connect_after_retry_wait_event()
        except bleak.exc.BleakDBusError as e:
            # Here we go again, parsing messages to determine *which* exception
            if e.args[0] == 'org.bluez.Error.InProgress':
                self.logger.info(
                    f"connect retry caught {e}, delaying this one a bit")
                await asyncio.sleep(IN_PROGRESS_HOLDOFF)
                await self._backend_connect_after_retry_wait_event()
            else:
                self.logger.exception(
                    'Failed to connect(), unrecognized exception.')
                raise
        except Exception:
            self.logger.exception(
                'Failed to connect(), unrecognized exception.')
            raise


    @property
    def _retry_is_active(self):
        return self._retry_since is not None

    def _retry_reset(self):
        self.logger.debug("Resetting retry timer")
        if self._retry_wait_task is not None:
            self._retry_wait_task.cancel()
            self._retry_wait_task = None
        self._retry_since = None
        self._retry_wait_event.clear()

    def _retry_start(self):
        self._retry_reset()
        self.logger.debug("Starting retry timer")
        self._retry_since = time.time()

    def _retry_delay(self) -> float:
        if self._retry_since is None:
            retval = 0
        else:
            dt = time.time() - self._retry_since
            if dt < self._retry_start_initial_delay:
                retval = 0
            elif self._retry_start_initial_delay <= dt < self._retry_start_long_delay:
                retval = self._retry_initial_delay
            else:
                retval = self._retry_long_delay
        return retval

    def _retry_set_timer(self):
        how_long = self._retry_delay()
        if how_long == 0:
            self._retry_wait_event.set()
        else:
            self._retry_wait_event.clear()
            self._retry_wait_task = asyncio.create_task(
                self._retry_waiter(how_long),
                name=f"_retry_waiter({how_long})")
            self.logger.info(
                f"Connect holdoff of {how_long} seconds "
                + task_for_log(self._retry_wait_task))

    # Potentially use loop.call_later
    # returns an asyncio.TimerHandle
    # th.cancel()
    # th.when() float in seconds, absolute

    async def _retry_waiter(self, how_long: float):
        assert how_long > 0
        try:
            t0 = time.time()
            await asyncio.sleep(how_long)
            dt = time.time() - t0
            self._retry_wait_event.set()
        except asyncio.CancelledError:
            pass
        finally:
            self._retry_wait_task = None

    # https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.add_done_callback
    # https://docs.python.org/3/library/asyncio-future.html#asyncio.Future.add_done_callback
    # add_done_callback(callback, *, context=None)
    #
    # The callback is called with the Future object as its only argument.
    #
    # An optional keyword-only context argument allows specifying a custom
    # contextvars.Context for the callback to run in.
    # The current context is used when no context is provided.

    def _generate_capture_release_done_callback(self):
        # Try without capturing self explicitly
        logger = self.logger.getChild('DoneCB')

        def capture_release_done_callback(fut: asyncio.Future):
            logger.debug(f"Entering done callback {task_for_log(fut)}")

            try:
                fut.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug(
                    f"client: {self._backend} addr type: {type(self._backend.address)}")
                logger.exception(f"Exception from {fut}")
                raise

            if (wt := self._retry_wait_task) is not None:
                wt.cancel()
                logger.info(
                    f"In {task_for_log(fut)}, canceled {task_for_log(wt)}")
            asyncio.create_task(
                self._capture_release_done_callback_async(
                    done_callback_from=fut))
            # logger.info(f"Leaving callback {task_for_log(fut)}")

        return capture_release_done_callback

    async def _capture_release_done_callback_async(self,
            done_callback_from: asyncio.Future):
        logger = self.logger.getChild('DoneCB.A')
        logger.debug(
            f"Entering async done callback {task_for_log(done_callback_from)}")
        if done_callback_from.cancelled():
            logger.debug(
                f"Done callback reports cancelled {task_for_log(done_callback_from)}")

        ll = LockLogger(lock=self._capture_queue_lock,
                        name='CaptureQueue').check()
        async with self._capture_queue_lock:
            ll.acquired()

            # Sanity checks
            if self._capture_queue.pending is None:
                logger.warning(
                    f"Nothing pending, but got {done_callback_from}.")
            if done_callback_from != self._pending_task:
                logger.error(
                    f"Pending {self._pending_task}, "
                    f"but got {done_callback_from}. "
                    "Removing anyway.")

            # Update to the new result
            self._pending_task = None
            cval = CaptureRequest.CAPTURE if self._backend.is_connected \
                else CaptureRequest.RELEASE
            self._capture_queue = CaptureQueue(
                    connected=cval,
                    pending=None,
                    target=self._capture_queue.target,
            )
            # The update with any needed action
            self._update_queue_and_events_have_lock()

        ll.released()
        # logger.info(
        #     f"Leaving async callback {task_for_log(done_callback_from)}")

    def _update_queue_and_events_have_lock(self):
        """
        Called in done_callback from a task to change connectivity
        as well as from disconnected_callback.

        NB: Only call while holding _capture_queue_lock
        """
        assert self._capture_queue_lock.locked(), \
                f"{self}._capture_queue_lock was not locked "

        logger = self.logger.getChild('Update')

        cq_on_entry = self._capture_queue
        if self.is_connected:
            current = CaptureRequest.CAPTURE
        else:
            current = CaptureRequest.RELEASE

        self._capture_queue = CaptureQueue(connected=current,
                                           pending=cq_on_entry.pending,
                                           target=cq_on_entry.target)
        logger.debug(
            "As {}connected, updated from {} to {} ".format(
                '' if self.is_connected else 'dis',
                cq_to_code(cq_on_entry),
                cq_to_code(self._capture_queue)
            ))

        self._maybe_initiate_action_have_lock(request=cq_on_entry.target)

        logger.debug(
            'After _maybe_initiate: was {} now {}'.format(
                cq_to_code(cq_on_entry),
                cq_to_code(self._capture_queue)
            ))

        #
        # Update the events
        #

        cq = self._capture_queue

        if cq.connected == CaptureRequest.CAPTURE:
            self._event_disconnected.clear()
            self._event_released.clear()
            self._event_connected.set()
            if cq.pending is None:
                self._event_captured.set()
                self._event_no_pending.set()
            else:
                self._event_captured.clear()
                self._event_no_pending.clear()
            logger.debug("Events set/cleared for CaptureRequest.CAPTURE")

        elif cq.connected == CaptureRequest.RELEASE:
            self._event_connected.clear()
            self._event_captured.clear()
            self._event_disconnected.set()
            if cq.pending is None:
                self._event_released.set()
                self._event_no_pending.set()
            else:
                self._event_released.clear()
                self._event_no_pending.clear()
            logger.debug("Events set/cleared for CaptureRequest.RELEASE")

        elif cq.connected is None:
            pass

        else:
            raise ValueError(
                "Update events: Current should only be CAPTURE or RELEASE, "
                f"not {cq}"
            )

    def _generate_disconnected_callback(self):
        # Try without capturing self explicitly
        logger = self.logger.getChild('DiscCB')

        # TODO: Python 3.11 introduces typing.Self
        def disconnected_callback(client: 'ManagedBleakClient'):
            logger.debug(f"Disconnected callback, create async task {client}")
            asyncio.create_task(
                self._disconnected_callback_async(disconnected_from=client))
            # logger.info(f"Leaving callback {client}")

        return disconnected_callback

    async def _disconnected_callback_async(self,
                                disconnected_from: 'ManagedBleakClient'):
        logger = self.logger.getChild('DiscCB.A')
        logger.debug(
            f"Entering async disconnected callback {disconnected_from}")

        ll = LockLogger(lock=self._capture_queue_lock,
                        name='CaptureQueue').check()
        async with self._capture_queue_lock:
            ll.acquired()
            # Update to the new result
            cval = CaptureRequest.CAPTURE if self._backend.is_connected \
                else CaptureRequest.RELEASE
            self._capture_queue = CaptureQueue(
                connected=cval,
                pending=self._capture_queue.pending,
                target=self._capture_queue.target,
            )
            # Then update with any needed action
            self._update_queue_and_events_have_lock()

        ll.released()
        if self._legacy_disconnected_callback is not None:
            logger.info("Calling legacy disconnected_callback")
            self._legacy_disconnected_callback(disconnected_from)
            logger.info("Returned from calling legacy disconnected_callback")
        # logger.info(f"Leaving async callback {disconnected_from}")

