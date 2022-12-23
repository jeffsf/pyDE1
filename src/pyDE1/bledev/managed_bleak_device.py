"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

Utilities that are specific to pyDE1 DE1 and scales

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import logging
import time
from typing import Optional, Union

from bleak import BLEDevice

import pyDE1.task_logger

from pyDE1.bledev.managed_bleak_client import CaptureQueue, CaptureRequest, \
    ManagedBleakClient, cq_to_code
from pyDE1.btcontrack import persist_connection_file, remove_connection_file
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager.event_manager import SubscribedEvent
from pyDE1.event_manager.events import (
    ConnectivityState, ConnectivityChange,
    DeviceAvailabilityState, DeviceAvailability, DeviceRole,
)

# The behavior of sending a ConnectivityChange notice is the same
# between the DE1 and the scales.
# It is assumed that there is
from pyDE1.exceptions import DE1APIValueError, DE1ValueError
from pyDE1.lock_logger import LockLogger
from pyDE1.utils import call_str, EventReadOnly


class ManagedBleakDevice:
    """
    Mixin to provide the behavior associated with a ManagedBleakClient
    in the context of DE1 or Scale implementations
    """

    # Renames
    #   prepare_for_connection          _prepare_for_connection
    #   initialize_after_connection     _initialize_after_connection
    #   _bleak_client                   _client

    def __init__(self):
        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger(self.__class__.__name__ )
        if not hasattr(self, '_role'):
            self._role = DeviceRole.UNKNOWN
        if not hasattr(self, '_name'):
            self._name = ''

        self._bleak_client: ManagedBleakClient = ManagedBleakClient(
            address_or_ble_device='',
            disconnected_callback=self._create_disconnected_callback(),
            on_change_callback=self._create_on_change_callback(),
            logger=self.logger.getChild('Client'),
        )

        self._event_connectivity = SubscribedEvent(
            self, adjust_payload=_resend_last_state_if_none)
        self._event_availability = SubscribedEvent(self)
        self._ready = asyncio.Event()
        self._ready_ro = EventReadOnly(self._ready)

        self._prepare_for_connection()

    def _prepare_for_connection(self):
        """
        Override in subclass as needed
        """
        pass

    async def _initialize_after_connection(self, hold_ready=False):
        """
        Override in subclass as needed
        :param hold_ready: Do not call _notify_ready() here if True
        """
        if not hold_ready:
            self._notify_ready()

    @property
    def is_captured(self) -> bool:
        return self._bleak_client.is_captured

    @property
    def is_released(self):
        return self._bleak_client.is_released

    @property
    def is_ready(self):
        return self._ready.is_set()

    @property
    def is_connected(self):
        """
        Legacy -- likely want is_captured or is_ready
        """
        return self._bleak_client.is_connected

    @property
    def connectivity_task_pending(self) -> bool:
        return self._bleak_client.connectivity_task_pending

    @property
    def active_request(self) -> Optional[CaptureRequest]:
        return self._bleak_client.active_request

    @property
    def event_captured(self) -> EventReadOnly:
        return self._bleak_client.event_captured

    @property
    def event_released(self) -> EventReadOnly:
        return self._bleak_client.event_released

    @property
    def event_ready(self) -> EventReadOnly:
        return self._ready_ro

    async def capture(self, timeout: Optional[float] = None) -> bool:
        return await self._bleak_client.capture(timeout=timeout)

    async def release(self, timeout: Optional[float] = None) -> bool:
        return await self._bleak_client.release(timeout=timeout)

    async def request_capture(self):
        return await self._bleak_client.request_capture()

    async def request_release(self):
        return await self._bleak_client.request_release()

    @property
    def connectivity_state(self)-> ConnectivityState:
        if self.is_ready:
            cs = ConnectivityState.READY
        else:
            cs = cq_to_cs(self._bleak_client._capture_queue)
        return cs

    @property
    def availability_state(self)-> DeviceAvailabilityState:
        das = cq_to_das(self._bleak_client._capture_queue)
        if das == DeviceAvailabilityState.CAPTURED and self.is_ready:
            das = DeviceAvailabilityState.READY
        return das

    @property
    def name(self):
        name = self._name if self._name else "{}_{}".format(
            self.__class__.__name__,
            self.address[-8:] if self.address else 'None')
        return name

    @property
    def address(self):
        return self._bleak_client.address

    @property
    def role(self):
        return self._role

    async def change_address(self,
                             address: Optional[Union[BLEDevice, str]]) -> bool:
        if isinstance(address, BLEDevice):
            self._name = address.name
        else:
            self._name = None
        changed = await self._bleak_client.change_address(address)
        if changed:
            self._event_connectivity.last_sent_clear()
        return changed

    ###
    ### End of public API
    ###

    # For HTTP API

    @property
    def connectivity(self):
        retval = ConnectivityEnum.NOT_CONNECTED
        if self.is_captured:
            if self._ready.is_set():
                retval = ConnectivityEnum.READY
            else:
                retval = ConnectivityEnum.CONNECTED
        return retval

    async def availability_setter(self, value):
        assert isinstance(value, CaptureRequest), \
            f"mode of {value} not a CaptureRequest "
        if value is CaptureRequest.CAPTURE:
            await self.request_capture()
        elif value is CaptureRequest.RELEASE:
            await self.request_release()
        else:
            raise DE1APIValueError(
                "Only CAPTURE and RELEASE can be set, not {value}")

    async def connectivity_setter(self, value):
        assert isinstance(value, ConnectivityEnum), \
            f"mode of {value} not a ConnectivityEnum "
        if value is ConnectivityEnum.CONNECTED:
            await self.request_capture()
        elif value is ConnectivityEnum.NOT_CONNECTED:
            await self.request_release()
        else:
            raise DE1APIValueError(
                "Only CONNECTED and NOT_CONNECTED can be set, "
                f"not {value}")

    # Internals

    def _create_disconnected_callback(self):
        """
        Override as needed
        """
        # device = self

        # def disconnected_callback(client: BleakClient) -> None:
        #     pass
        #
        # return disconnected_callback

        return None

    def _create_on_change_callback(self):

        def on_change_callback(client: ManagedBleakClient,
                               previous: CaptureQueue,
                               current: CaptureQueue) -> None:
            arrival_time = time.time()

            self.logger.debug(
                "[{:05.3f}] on_change_callback(<MBC>, {}, {}) {}".format(
                    arrival_time % 10,
                    cq_to_code(previous),
                    cq_to_code(current),
                    call_str()
                ))


            asyncio.create_task(self._on_change_callback_async(
                arrival_time=arrival_time,
                client=client,
                previous=previous,
                current=current))

        return on_change_callback

    async def _on_change_callback_async(self,
                                        arrival_time: Optional[float],
                                        client: ManagedBleakClient,
                                        previous: CaptureQueue,
                                        current: CaptureQueue) -> None:

        if arrival_time is None:
            arrival_time= time.time()

        previous_das = cq_to_das(previous)
        current_das = cq_to_das(current)

        previous_cs = cq_to_cs(previous)
        current_cs = cq_to_cs(current)


        # These are strings for logging, not used for logic
        pss = previous_cs if previous_cs not in (
            ConnectivityState.UNKNOWN, None) else f"({cq_to_code(previous)})"
        css = current_cs if current_cs not in (
            ConnectivityState.UNKNOWN, None) else f"({cq_to_code(current)})"

        self.logger.debug(f"Change from {pss} to {css}")

        # NB: Even though the CaptureQueue may have changed,
        # the ConnectivityState may not have changed

        if (self.is_ready
                and current_cs != ConnectivityState.CONNECTED):
            self._notify_not_ready()

        if (not self.is_ready
                and current_cs == ConnectivityState.CONNECTED
                and previous_cs != ConnectivityState.CONNECTED):
            pyDE1.task_logger.create_task(
                self._initialize_after_connection(),
                logger=self.logger,
                message=f"Exception in initialize_after_connection()")

        if (current_cs == ConnectivityState.DISCONNECTED
                and previous_cs != ConnectivityState.DISCONNECTED):
            self._prepare_for_connection()

        self._send_device_availability(arrival_time=arrival_time,
                                       new_state=current_das)
        self._send_connectivity_change(arrival_time=arrival_time,
                                       new_state=current_cs)

        if current_cs in (ConnectivityState.CONNECTING,
                          ConnectivityState.CONNECTED,
                          ConnectivityState.READY):
            try:
                persist_connection_file(self.address)
            except DE1ValueError as e:
                self.logger.exception(
                    "Connection filename error: "
                    f"{self.name} {self.role} at {self.address}",
                    exc_info=e,
                )
                raise e
        elif current_cs == ConnectivityState.DISCONNECTED:
            remove_connection_file(self.address)

    # Helper method to populate a ConnectivityChange

    def _connectivity_change(self, arrival_time: float,
                             state: ConnectivityState):
        return ConnectivityChange(arrival_time=arrival_time,
                                  state=state,
                                  id=self.address,
                                  name=self.name)

    def _send_connectivity_change(self, arrival_time: float,
                                  new_state: ConnectivityState):
        """
        Converts the current CaptureQueue into a ConnectivityState
        and creates a task to send it using _connectivity_change.
        If CaptureState.UNKNOWN returned by cq_to_cs(),
        use the previously-sent value if there is one.
        """

        send_state = new_state

        if send_state == ConnectivityState.UNKNOWN:
            try:
                send_state = self._event_connectivity.last_sent.state
            except AttributeError:
                pass
                # This is expected on the first call after initialization
                # self._logger.warning(
                #     "Connectivity last sent of "
                #     f"{self._event_connectivity.last_sent}, "
                #     "using UNKNOWN rather than last-sent state")

        asyncio.create_task(
            self._event_connectivity.publish(
                self._connectivity_change(arrival_time=arrival_time,
                                          state=send_state)))

    @property
    def device_availability_last_sent(self):
        return self._event_availability.last_sent.as_json()

    def _device_availability(self, arrival_time: float,
                             state: DeviceAvailabilityState):
        return DeviceAvailability(arrival_time=arrival_time,
                                  role=self.role,
                                  state=state,
                                  id=self.address,
                                  name=self.name)

    def _send_device_availability(self, arrival_time: float,
                                  new_state: DeviceAvailabilityState):
        """
        Sends DeviceAvailability
        """
        asyncio.create_task(
            self._event_availability.publish(
                self._device_availability(arrival_time=arrival_time,
                                          state=new_state)))


    def _notify_ready(self):
        self._ready.set()
        # Send the same way to prevent things from getting out of order
        self._send_device_availability(
            arrival_time=time.time(),
            new_state=DeviceAvailabilityState.READY)
        self._send_connectivity_change(arrival_time=time.time(),
                                       new_state=ConnectivityState.READY)

        self.logger.info("Ready")

    def _notify_not_ready(self):
        self._ready.clear()
        self._send_device_availability(
            arrival_time=time.time(),
            new_state=DeviceAvailabilityState.NOT_READY)
        self._send_connectivity_change(arrival_time=time.time(),
                                       new_state=ConnectivityState.NOT_READY)

class ClassChangeException(RuntimeError):
    pass

class ClassChangeLeaveException(ClassChangeException):
    pass

class ClassChangeAdoptException(ClassChangeException):
    pass


# Use as decorator, such as
#    @class_changer_generic_class
#    class ParentClass (ManagedBleakDevice, ClassChanger):
#        pass
def class_changer_generic_class(cls: 'ClassChanger'):
    cls._class_changer_generic_class = cls
    return cls

class ClassChanger:
    """
    NB: This should "be first" in the list of inherited classes
    See: https://stackoverflow.com/questions/9575409/
        calling-parent-class-init-with-multiple-inheritance-whats-the-right-way

    This is a mixin class that supports a limited ability to change between
    a generic parent class and various subclasses.  The intended application
    is for scales where the desired subclass is not able to be determined
    until the signature is seen over Bluetooth.  Changing out the object
    would either need all references to the prior instance to be updated
    or a proxy object hiding the instance of the moment behind an unchanging
    set of references for consumers.

    The basic flow of changing class is:
        * instance._leave_class() is called while the current class is known
        * instance.__class__ gets set to a new subclass
        * instance._adopt_class() is called to set up the instance,
          ready to call instance._initialize_after_connection()
          as the new class

    Calling _leave_class() on an instance should restore the instance to a state
    that is similar to that returned by GenericClass().  As this will sometimes
    be called as a result of establishing a Bluetooth connection, the state
    of that connection probably should not be modified.  This behavior is only
    available when a subclass of cls._class_changer_generic_class and not that
    class itself.

    Calling _adopt_class() on an instance should update either an instance
    of GenericClass or one on which _leave_class() has just been called
    to one that is fully functional based on its recently changed class
    and ready for _initialize_on_connect() to be called.

    Because of this class-changing behavior, some functionality isn't available
    until the class change completes. This is TBD right now.

    NB: This is fragile voodoo and subject to the internals of Python changing
    """

    # Set to the generic class for the hierarchy
    # Python 3.11 and later supports typing.Self

    _class_changer_generic_class = None

    def __init__(self, *args, **kwargs):
        super(ClassChanger, self).__init__(*args, **kwargs)
        self._class_change_lock = asyncio.Lock()

    def _is_generic_class(self):
        return type(self) == self._class_changer_generic_class

    def _is_descendant_class(self):
        return (not self._is_generic_class()
                and isinstance(self, self._class_changer_generic_class))

    async def _leave_class(self):
        if self._is_generic_class():
            return
        else:
            # do the work here
            pass

    async def _adopt_class(self):
        # should be able to adopt the generic class, even if a noop
        # do the work here
        pass

    async def _change_class(self, new_class: type):
        old_class_name = self.__class__.__name__
        new_class_name = new_class.__name__
        try:
            logger = self.logger
        except AttributeError:
            logger = logging.getLogger(old_class_name)
        if not issubclass(new_class, self._class_changer_generic_class):
            raise ClassChangeException(
                "Can't change from {} to {} as not a {}".format(
                    type(self), new_class, self._class_changer_generic_class
                ))
        ll = LockLogger(self._class_change_lock, 'ClassChange').check()
        async with self._class_change_lock:
            ll.acquired()
            logger.info(
                f"Leaving {old_class_name} for {new_class_name}")
            await self._leave_class()
            self.__class__ = new_class
            await self._adopt_class()
            logger.info(
                f"Changed from {old_class_name} to {new_class_name}")
        ll.released()


def cq_to_cs(cq: CaptureQueue) -> Optional[ConnectivityState]:
    """
    Given a CaptureQueue instance, return the "matching" ConnectivityState
    or, if indeterminate what will happen next (cancel pending), return None
    """
    cs = ConnectivityState.UNKNOWN

    # Nothing pending, current matches target

    if cq == CaptureQueue(CaptureRequest.CAPTURE, None,
                          CaptureRequest.CAPTURE):
        cs = ConnectivityState.CONNECTED

    elif cq == CaptureQueue(CaptureRequest.RELEASE, None,
                            CaptureRequest.RELEASE):
        cs = ConnectivityState.DISCONNECTED

    # Nothing pending, current != target

    elif cq.pending is None:

        if cq.target == CaptureRequest.CAPTURE:
            cs = ConnectivityState.CONNECTING

        elif cq.target == CaptureRequest.RELEASE:
            cs = ConnectivityState.DISCONNECTING

        # Nothing pending, no target

        elif cq.target is None:
            if cq.connected is None:
                cs = ConnectivityState.INITIAL  # Initial state
            elif cq.connected == CaptureRequest.CAPTURE:

                cs = ConnectivityState.CONNECTED
            elif cq.connected == CaptureRequest.RELEASE:
                cs = ConnectivityState.DISCONNECTED

    # Something pending

    elif cq.pending == CaptureRequest.CAPTURE:
        cs = ConnectivityState.CONNECTING

    elif cq.pending == CaptureRequest.RELEASE:
        cs = ConnectivityState.DISCONNECTING

    # Pending cancel
    # No information in cq as to what it was before, return None

    elif cq.pending == CaptureRequest.CANCEL:
        cs = ConnectivityState.UNKNOWN

    else:
        raise RuntimeError(f"Logic fall-through with {cq}")

    return cs


def cq_to_das(cq: CaptureQueue) -> DeviceAvailabilityState:
    """
    Given a CaptureQueue instance, return the "matching" DeviceAvailabilityState

    NB: This never returns READY or NOT_READY
    """
    das = DeviceAvailabilityState.UNKNOWN

    # Nothing pending, current matches target

    if cq == CaptureQueue(CaptureRequest.CAPTURE, None,
                          CaptureRequest.CAPTURE):
        das = DeviceAvailabilityState.CAPTURED

    elif cq == CaptureQueue(CaptureRequest.RELEASE, None,
                            CaptureRequest.RELEASE):
        das = DeviceAvailabilityState.RELEASED

    # Nothing pending, current != target

    elif cq.pending is None:

        if cq.target == CaptureRequest.CAPTURE:
            das = DeviceAvailabilityState.CAPTURING

        elif cq.target == CaptureRequest.RELEASE:
            das = DeviceAvailabilityState.RELEASING

        # Nothing pending, no target

        elif cq.target is None:
            if cq.connected is None:
                das = DeviceAvailabilityState.INITIAL  # Initial state
            elif cq.connected == CaptureRequest.CAPTURE:

                das = DeviceAvailabilityState.CAPTURED
            elif cq.connected == CaptureRequest.RELEASE:
                das = DeviceAvailabilityState.RELEASED

    # Something pending

    elif cq.pending == CaptureRequest.CAPTURE:
        das = DeviceAvailabilityState.CAPTURING

    elif cq.pending == CaptureRequest.RELEASE:
        das = DeviceAvailabilityState.RELEASING

    # Pending cancel

    elif cq.pending == CaptureRequest.CANCEL:
        if cq.target == CaptureRequest.CAPTURE:
            das = DeviceAvailabilityState.CAPTURING
        elif cq.target == CaptureRequest.RELEASE:
            das = DeviceAvailabilityState.RELEASING
        else:
            das = DeviceAvailabilityState.UNKNOWN

    else:
        raise RuntimeError(f"Logic fall-through with {cq}")

    return das


def _resend_last_state_if_none(se: SubscribedEvent,
                               payload: ConnectivityChange):
    if payload.state is ConnectivityState.UNKNOWN:
        if (old := se.last_sent) is not None:
            payload.state = old.state
        else:
            payload.state = ConnectivityState.UNKNOWN

