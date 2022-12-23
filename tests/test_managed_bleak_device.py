"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import gc
import inspect
import logging
import os
import time
import traceback
from typing import Optional, Union

import bleak
import pytest

from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock, PropertyMock, patch

from bleak import BLEDevice

import pyDE1
from pyDE1.de1 import DE1   # Needed to smooth imports
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager import EventPayload, SubscribedEvent
from pyDE1.event_manager.events import (
    ConnectivityState, ConnectivityChange,
    DeviceAvailabilityState, DeviceAvailability,
)
from pyDE1.bledev.managed_bleak_client import (
    CaptureRequest, ManagedBleakClient, cq_from_code, cq_to_code
)
from pyDE1.bledev.managed_bleak_device import (
    cq_to_cs, ManagedBleakDevice, cq_to_das
)
from pyDE1.exceptions import DE1NoAddressError

"""
Should show "next" rather than "terminal" if different
"""
cq_to_cs_mapping = {
    'CNC': ConnectivityState.CONNECTED,
    'CCC': ConnectivityState.CONNECTING,
    'CRC': ConnectivityState.DISCONNECTING,
    'CXC': ConnectivityState.UNKNOWN,  # Depends on previous
    'CNR': ConnectivityState.DISCONNECTING,
    'CCR': ConnectivityState.CONNECTING,
    'CRR': ConnectivityState.DISCONNECTING,
    'CXR': ConnectivityState.UNKNOWN,  # Depends on previous
    #
    'RNC': ConnectivityState.CONNECTING,
    'RCC': ConnectivityState.CONNECTING,
    'RRC': ConnectivityState.DISCONNECTING,
    'RXC': ConnectivityState.UNKNOWN,  # Depends on previous
    'RNR': ConnectivityState.DISCONNECTED,
    'RCR': ConnectivityState.CONNECTING,
    'RRR': ConnectivityState.DISCONNECTING,
    'RXR': ConnectivityState.UNKNOWN,  # Depends on previous
    #
    'NNC': ConnectivityState.CONNECTING,
    'NCC': ConnectivityState.CONNECTING,
    'NRC': ConnectivityState.DISCONNECTING,
    'NXC': ConnectivityState.UNKNOWN,  # Depends on previous
    'NNR': ConnectivityState.DISCONNECTING,
    'NCR': ConnectivityState.CONNECTING,
    'NRR': ConnectivityState.DISCONNECTING,
    'NXR': ConnectivityState.UNKNOWN,  # Depends on previous
    #
    'CNN': ConnectivityState.CONNECTED,
    'CCN': ConnectivityState.CONNECTING,
    'CRN': ConnectivityState.DISCONNECTING,
    'CXN': ConnectivityState.UNKNOWN,  # Depends on previous
    'RNN': ConnectivityState.DISCONNECTED,
    'RCN': ConnectivityState.CONNECTING,
    'RRN': ConnectivityState.DISCONNECTING,
    'RXN': ConnectivityState.UNKNOWN,  # Depends on previous
    'NNN': ConnectivityState.INITIAL,  # initial state
    'NCN': ConnectivityState.CONNECTING,
    'NRN': ConnectivityState.DISCONNECTING,
    'NXN': ConnectivityState.UNKNOWN,  # Depends on previous
}

def test_cq_to_cs():
    for c in 'CRN':
        for p in 'NCRX':
            for t in 'CRN':
                code = c+p+t
                cq = cq_from_code(code)
                cs = cq_to_cs(cq)
                # print(f"{code} {cs}")
                assert cs == cq_to_cs_mapping[code], f"Testing {code}"


cq_to_das_mapping = {
    'CNC': DeviceAvailabilityState.CAPTURED,
    'CCC': DeviceAvailabilityState.CAPTURING,
    'CRC': DeviceAvailabilityState.RELEASING,
    'CXC': DeviceAvailabilityState.CAPTURING,
    'CNR': DeviceAvailabilityState.RELEASING,
    'CCR': DeviceAvailabilityState.CAPTURING,
    'CRR': DeviceAvailabilityState.RELEASING,
    'CXR': DeviceAvailabilityState.RELEASING,
    #
    'RNC': DeviceAvailabilityState.CAPTURING,
    'RCC': DeviceAvailabilityState.CAPTURING,
    'RRC': DeviceAvailabilityState.RELEASING,
    'RXC': DeviceAvailabilityState.CAPTURING,
    'RNR': DeviceAvailabilityState.RELEASED,
    'RCR': DeviceAvailabilityState.CAPTURING,
    'RRR': DeviceAvailabilityState.RELEASING,
    'RXR': DeviceAvailabilityState.RELEASING,
    #
    'NNC': DeviceAvailabilityState.CAPTURING,
    'NCC': DeviceAvailabilityState.CAPTURING,
    'NRC': DeviceAvailabilityState.RELEASING,
    'NXC': DeviceAvailabilityState.CAPTURING,
    'NNR': DeviceAvailabilityState.RELEASING,
    'NCR': DeviceAvailabilityState.CAPTURING,
    'NRR': DeviceAvailabilityState.RELEASING,
    'NXR': DeviceAvailabilityState.RELEASING,
    #
    'CNN': DeviceAvailabilityState.CAPTURED,
    'CCN': DeviceAvailabilityState.CAPTURING,
    'CRN': DeviceAvailabilityState.RELEASING,
    'CXN': DeviceAvailabilityState.UNKNOWN,
    'RNN': DeviceAvailabilityState.RELEASED,
    'RCN': DeviceAvailabilityState.CAPTURING,
    'RRN': DeviceAvailabilityState.RELEASING,
    'RXN': DeviceAvailabilityState.UNKNOWN,
    'NNN': DeviceAvailabilityState.INITIAL,  # initial state
    'NCN': DeviceAvailabilityState.CAPTURING,
    'NRN': DeviceAvailabilityState.RELEASING,
    'NXN': DeviceAvailabilityState.UNKNOWN,
}


def test_cq_to_das():
    for c in 'CRN':
        for p in 'NCRX':
            for t in 'CRN':
                code = c+p+t
                cq = cq_from_code(code)
                cs = cq_to_das(cq)
                # print(f"{code} {cs}")
                assert cs == cq_to_das_mapping[code], f"Testing {code}"


@pytest.fixture
def mock_bleak_backend(monkeypatch):

    logger = logging.getLogger('mock_bleak_backend')

    target_class = bleak.get_platform_client_backend_type()

    class MockControl():
        def __init__(self):
            self.is_connected = None
            self.turnstile_connect = asyncio.Event()
            self.fail_connect = False
            self.turnstile_disconnect = asyncio.Event()
            self.turnstiles_active = True

        def open_turnstiles(self):
            self.turnstile_connect.set()
            self.turnstile_disconnect.set()

        def close_turnstiles(self):
            self.turnstile_connect.clear()
            self.turnstile_disconnect.clear()

    mc = MockControl()

    def mock_is_connected_getter(*args, **kwargs):
        try:
            retval = mc.is_connected
        except AttributeError:
            retval = None
        return retval

    monkeypatch.setattr(target_class, 'is_connected',
                        property(fget=mock_is_connected_getter))

    async def mock_connect(*args, **kwargs):
        if mc.turnstiles_active:
            try:
                await mc.turnstile_connect.wait()
                mc.turnstile_connect.clear()
                if not mc.fail_connect:
                    mc.is_connected = True
            except asyncio.CancelledError:
                mc.turnstile_connect.clear()
        else:
            if not mc.fail_connect:
                mc.is_connected = True
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'connect',
                        mock_connect)

    async def mock_disconnect(client_backend, *args, **kwargs):
        if mc.turnstiles_active:
            try:
                await mc.turnstile_disconnect.wait()
                mc.turnstile_disconnect.clear()
                mc.is_connected = False
                if client_backend._disconnected_callback is not None:
                    client_backend._disconnected_callback(client_backend)
                else:
                    logger.info(
                        f'No _disconnected_callback for {client_backend}')
            except asyncio.CancelledError:
                mc.turnstile_disconnect.clear()
        else:
            mc.is_connected = False
            if client_backend._disconnected_callback is not None:
                client_backend._disconnected_callback(client_backend)
            else:
                logger.info(
                    f'No _disconnected_callback for {client_backend}')
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'disconnect',
                        mock_disconnect)

    return mc


@pytest.mark.asyncio
async def test_backend_mocks(mock_bleak_backend):

    dcb = MagicMock()

    mbc = ManagedBleakClient(address_or_ble_device=None,
                             disconnected_callback=dcb)

    mock_bleak_backend.client = mbc

    assert mbc.is_connected == None
    mock_bleak_backend.is_connected = True
    assert mbc.is_connected is True
    mock_bleak_backend.is_connected = 'abc'
    assert mbc.is_connected == 'abc'
    mock_bleak_backend.fail_connect = False
    mock_bleak_backend.turnstile_connect.set()
    mock_bleak_backend.turnstile_disconnect.set()
    with pytest.raises(DE1NoAddressError):
        await mbc.capture(timeout=1)
    await mbc.change_address('11:22:33:44:55:66')
    assert mbc.address == '11:22:33:44:55:66'
    assert dcb.call_count == 1
    assert not mock_bleak_backend.turnstile_disconnect.is_set()
    mock_bleak_backend.turnstile_disconnect.set()
    await mbc.capture(timeout=1)
    assert mbc.is_captured
    await mbc.release(timeout=1)
    assert mbc.is_released
    assert dcb.call_count == 2


@pytest.fixture
def mock_de1_comms(monkeypatch):

    logger = logging.getLogger('mock_de1_comms')

    class MockControl:

        def __init__(self):
            self.de1: DE1 = None
            self.turnstile_ready = asyncio.Event()
            self.mock_initialize_mock = Mock()

    mc = MockControl()

    async def mock_initialize_inner(self):
        try:
            await mc.turnstile_ready.wait()
            mc.turnstile_ready.clear()
            self._notify_ready()
        except asyncio.CancelledError:
            mc.turnstile_ready.clear()
        return True

    mc.mock_initialize_mock.side_effect = mock_initialize_inner

    async def mock_initialize(*args, **kwargs):
        return await mc.mock_initialize_mock(*args, **kwargs)

    monkeypatch.setattr(DE1, '_initialize_after_connection',
                        mock_initialize)

    async def mock_event_publish(self, payload: EventPayload):
        logger.debug(f"Notify {payload.as_json()}")

    monkeypatch.setattr(pyDE1.event_manager.SubscribedEvent, 'publish',
                        mock_event_publish)

    return mc


@pytest.fixture
def mock_de1_prepare(monkeypatch):

    logger = logging.getLogger('mock_de1_prepare_initialize')

    class MockControl:

        def __init__(self):
            self.mock_pfc = Mock(wraps=DE1._prepare_for_connection,
                                 spec=DE1._prepare_for_connection)

    mc = MockControl()

    def wrap_pfc(*args, **kwargs):
        return mc.mock_pfc(*args, **kwargs)

    monkeypatch.setattr(DE1, '_prepare_for_connection',
                        wrap_pfc)

    return mc


@pytest.mark.asyncio
async def test_de1_managed_bleak_device(fresh_de1,
                                        mock_bleak_backend,
                                        mock_de1_comms,
                                        mock_de1_prepare,
                                        caplog):
    """
    Believed to check:
        .prepare_for_connection is called as expected
        .initialize_after_connection is called as expected
        .is_captured
        .is_released
        .is_ready
        .is_connected
        .connectivity_task_pending
        .active_request
        .event_captured
        .event_released
        .capture()
        .release()
        .request_capture()
        .request_release()
        .address
        .set_address()
        Creation and removal of the BTID file
        .connectivity

    Not yet:
        set_address(BLEDevice)
        .name
        .connectivity_setter
    """

    # caplog.set_level(logging.INFO)

    # logger = logging.getLogger()

    mock_bleak_backend.open_turnstiles()
    de1 = DE1()
    assert mock_de1_prepare.mock_pfc.call_count == 1
    assert de1.connectivity_state == ConnectivityState.INITIAL

    mock_bleak_backend.client = de1._bleak_client

    use_address = '11:22:33:44:55:66'
    btid_fname = '112233445566.btid'
    btid_file = Path('/var/lib/pyde1', btid_fname)
    try:
        os.remove(btid_file)
    except FileNotFoundError:
        pass
    assert not btid_file.exists()
    await de1.change_address(use_address)
    assert de1.address == '11:22:33:44:55:66'
    assert not btid_file.exists()
    assert mock_de1_prepare.mock_pfc.call_count == 2

    assert not de1.is_connected
    assert not de1.is_ready
    assert not de1.is_captured
    assert not de1.is_released
    assert de1.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert de1.connectivity_state == ConnectivityState.INITIAL

    mock_bleak_backend.open_turnstiles()

    await de1.release(timeout=1)
    assert not de1.is_connected
    assert not de1.is_ready
    assert not de1.is_captured
    assert     de1.is_released
    assert not btid_file.exists()
    assert de1.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert de1.connectivity_state == ConnectivityState.DISCONNECTED

    assert mock_de1_comms.mock_initialize_mock.call_count == 0

    mock_bleak_backend.open_turnstiles()

    await de1.capture(timeout=1)
    assert     de1.is_connected
    assert not de1.is_ready
    assert     de1.is_captured
    assert not de1.is_released
    assert     btid_file.exists()
    assert de1.connectivity == ConnectivityEnum.CONNECTED
    assert de1.connectivity_state == ConnectivityState.CONNECTED
    # Should have already been called, but holding for turnstile
    assert mock_de1_comms.mock_initialize_mock.call_count == 1

    mock_de1_comms.turnstile_ready.set()
    await asyncio.sleep(0.100)
    assert     de1.is_connected
    assert     de1.is_ready
    assert     de1.is_captured
    assert not de1.is_released
    assert     btid_file.exists()
    assert de1.connectivity == ConnectivityEnum.READY
    assert de1.connectivity_state == ConnectivityState.READY
    assert mock_de1_comms.mock_initialize_mock.call_count == 1

    mock_bleak_backend.open_turnstiles()
    assert mock_de1_prepare.mock_pfc.call_count == 3
    await de1.release()
    assert not de1.is_connected
    assert not de1.is_ready
    assert not de1.is_captured
    assert     de1.is_released
    assert not btid_file.exists()
    assert de1.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert de1.connectivity_state == ConnectivityState.DISCONNECTED
    assert mock_de1_prepare.mock_pfc.call_count == 4

    assert mock_de1_comms.mock_initialize_mock.call_count == 1

    mock_bleak_backend.turnstile_connect.clear()
    mock_bleak_backend.turnstile_disconnect.clear()

    assert not de1.connectivity_task_pending
    assert de1.active_request == CaptureRequest.RELEASE
    await de1.request_capture()
    assert de1.active_request == CaptureRequest.CAPTURE
    assert de1.connectivity_task_pending
    assert de1.connectivity_state == ConnectivityState.CONNECTING

    mock_bleak_backend.open_turnstiles()
    await asyncio.wait_for(de1.event_captured.wait(), timeout=0.100)
    assert not de1.connectivity_task_pending
    assert de1.active_request == CaptureRequest.CAPTURE
    assert de1.connectivity_state == ConnectivityState.CONNECTED

    mock_bleak_backend.turnstile_connect.clear()
    mock_bleak_backend.turnstile_disconnect.clear()

    assert not de1.connectivity_task_pending
    assert de1.active_request == CaptureRequest.CAPTURE
    await de1.request_release()
    assert de1.active_request == CaptureRequest.RELEASE
    assert de1.connectivity_state == ConnectivityState.DISCONNECTING
    assert de1.connectivity_task_pending

    mock_bleak_backend.open_turnstiles()
    await asyncio.wait_for(de1.event_released.wait(), timeout=0.100)
    assert not de1.connectivity_task_pending
    assert de1.active_request == CaptureRequest.RELEASE
    assert de1.connectivity_state == ConnectivityState.DISCONNECTED


@pytest.fixture
def fresh_de1():
    DE1.__it__ = None

@pytest.mark.asyncio
async def test_de1_from_ble_device(fresh_de1,
                                   mock_bleak_backend,
                                   mock_de1_comms,
                                   mock_de1_prepare,
                                   caplog):
    """
    Tests:
        .set_address(BLEDevice)
        .name
        .connectivity_setter
        .ready_event
    """

    mock_bleak_backend.open_turnstiles()
    de1 = DE1()
    assert mock_de1_prepare.mock_pfc.call_count == 1

    mock_bleak_backend.client = de1._bleak_client

    use_address = '11:22:33:44:55:66'
    use_name = 'Confirm this'
    btid_fname = '112233445566.btid'
    btid_file = Path('/var/lib/pyde1', btid_fname)
    try:
        os.remove(btid_file)
    except FileNotFoundError:
        pass
    assert not btid_file.exists()

    ble_device = BLEDevice(address=use_address, name=use_name)

    await de1.change_address(ble_device)
    assert de1.address == use_address
    assert de1.name == use_name
    assert not btid_file.exists()
    assert mock_de1_prepare.mock_pfc.call_count == 2

    assert not de1.is_connected
    assert not de1.is_ready
    assert not de1.is_captured
    assert not de1.is_released
    assert de1.connectivity == ConnectivityEnum.NOT_CONNECTED

    mock_bleak_backend.open_turnstiles()
    mock_de1_comms.turnstile_ready.clear()
    await de1.connectivity_setter(ConnectivityEnum.CONNECTED)
    await asyncio.wait_for(de1.event_captured.wait(), timeout=0.100)
    assert not de1.is_ready
    assert de1.is_captured
    mock_de1_comms.turnstile_ready.set()
    await asyncio.wait_for(de1.event_ready.wait(), timeout=0.100)
    assert de1.is_ready

    mock_bleak_backend.open_turnstiles()
    mock_de1_comms.turnstile_ready.clear()
    await de1.connectivity_setter(ConnectivityEnum.NOT_CONNECTED)
    await asyncio.wait_for(de1.event_released.wait(), timeout=0.100)
    assert not de1.is_ready
    assert not de1.is_captured

@pytest.fixture
def mock_subscribed_event_publish(monkeypatch):

    logger = logging.getLogger('SE.publish')

    async def mock_event_publish(self, payload: EventPayload):
        # Warnings about not being awaited seem to be due to
        # running off the end of the test before the task executes
        if isinstance(payload, ConnectivityChange):
            try:
                psn = payload.state.name
            except AttributeError:
                psn = f">>>>>{payload.state}<<<<<"
            logger.info('[{:05.3f}] ConnectivityChange: 0x{:x} "{}" {}'.format(
                payload.arrival_time % 10,
                id(self.sender),
                payload.id,
                psn,
            ))
        else:
            logger.info(f"{payload.as_json()} via {self.sender}")

    monkeypatch.setattr(pyDE1.event_manager.SubscribedEvent, 'publish',
                        mock_event_publish)


class SkeletalMBD (ManagedBleakDevice):

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger
        super(SkeletalMBD, self).__init__()
    
    def _prepare_for_connection(self):
        self.logger.info(f"prepare_for_connection() 0x{id(self):x}")
        
    async def _initialize_after_connection(self, hold_ready=False):
        self.logger.info(f"initialize_after_connection() 0x{id(self):x}")
        self._notify_ready()


@pytest.mark.asyncio
async def test_skeletal_mbd_init(monkeypatch,
                                 mock_subscribed_event_publish,
                                 caplog):
    # tlname = inspect.currentframe().f_code.co_name
    tlname = '===>'
    tl = logging.getLogger(tlname)
    logger = logging.getLogger('MBD')
    caplog.set_level(logging.DEBUG, logger.name)
    caplog.set_level(logging.INFO, 'SE.publish')
    caplog.set_level(logging.DEBUG, tlname)

    tl.debug("About to create")
    mbd = SkeletalMBD(logger=logger)
    tl.debug(f"Created {mbd}")
    await asyncio.sleep(0.100)

    assert not mbd.is_connected
    assert not mbd.is_released
    assert not mbd.is_captured
    assert not mbd.is_ready

    assert mbd.connectivity_state == ConnectivityState.INITIAL


async def log_payload(payload: EventPayload):
    logger = logging.getLogger('Notify.Payload')
    if isinstance(payload, ConnectivityChange):
        try:
            psn = payload.state.name
        except AttributeError:
            psn = f">>>>>{payload.state}<<<<<"
        logger.debug('[{:05.3f}] ConnectivityChange: {} "{}" {}'.format(
            payload.arrival_time % 10,
            payload.sender,
            payload.id,
            psn,
        ))
    else:
        logger.debug(f"{payload.as_json()}")

@pytest.fixture
def mock_send_to_outbound_pipes(monkeypatch):

    class MockControl:

        def __init__(self):
            self.notify = False
            self.connectivity_sent = []

    mc = MockControl()

    async def send_to_outbound_pipes_mock(payload: EventPayload):
        if isinstance(payload, ConnectivityChange):
            mc.connectivity_sent.append(
                (payload.state.name, payload.id,)
            )
        if mc.notify:
            logger = logging.getLogger('Notify.Outbound')
            logger.debug(f"Sent {payload}")

    # Need to patch at origin, not as imported up a level
    monkeypatch.setattr(pyDE1.event_manager.event_manager,'send_to_outbound_pipes',
                        send_to_outbound_pipes_mock)

    return mc

@pytest.mark.asyncio
async def test_skeletal_mbd_set_addr(mock_bleak_backend,
                                     mock_send_to_outbound_pipes,
                                     caplog):

    mock_bleak_backend.turnstiles_active = False

    logger = logging.getLogger('MBD')
    caplog.set_level(logging.INFO, logger.name)

    # tlname = inspect.currentframe().f_code.co_name
    tlname = '===>'
    tl = logging.getLogger(tlname)
    caplog.set_level(logging.DEBUG, tlname)
    caplog.set_level(logging.DEBUG, 'Notify.Payload')


    mbd = SkeletalMBD(logger=logger)
    await mbd._event_connectivity.subscribe(log_payload)

    assert not mbd.is_connected
    assert not mbd.is_released
    assert not mbd.is_captured
    assert not mbd.is_ready
    assert mbd.connectivity_state == ConnectivityState.INITIAL

    check_sent = list(zip(['INITIAL'], [""]))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

    assert mbd.address == ''
    tl.debug("Setting address")
    use_address = '11:22:33:44:55:66'
    await mbd.change_address(use_address)
    assert mbd.address == use_address

    assert not mbd.is_connected
    assert not mbd.is_released
    assert not mbd.is_captured
    assert not mbd.is_ready
    assert mbd.connectivity_state == ConnectivityState.INITIAL

    check_sent = list(zip(
        ['DISCONNECTING', 'DISCONNECTING', 'DISCONNECTING', 'DISCONNECTED',
         'INITIAL'],
        ['']*4 + [use_address]))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

    tl.debug("Starting capture")
    await mbd.capture(1.0)
    assert mbd.connectivity_state in (ConnectivityState.CONNECTED,
                                      ConnectivityState.READY)
    await asyncio.wait_for(mbd.event_ready.wait(), 0.100)
    assert mbd.connectivity_state == ConnectivityState.READY

    check_sent = list(zip(
        ['CONNECTING', 'CONNECTED', 'READY',],
        [use_address]*3))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

    tl.debug("Starting release")
    await mbd.release(1.0)
    tl.debug("Done")

    check_sent = list(zip(
        ['NOT_READY', 'DISCONNECTING', 'DISCONNECTING', 'DISCONNECTING',
        'DISCONNECTED'],
        [use_address]*5))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

    tl.debug("Starting change of address")
    next_address = 'aa:bb:cc:dd:ee:ff'
    await mbd.change_address(next_address)
    assert not mbd.is_connected
    assert not mbd.is_released
    assert not mbd.is_captured
    assert not mbd.is_ready
    assert mbd.connectivity_state == ConnectivityState.INITIAL

    check_sent = list(zip(
        ['INITIAL'],
        [next_address]))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

    tl.debug("Starting new capture")
    await mbd.capture(1.0)
    assert mbd.connectivity_state in (ConnectivityState.CONNECTED,
                                      ConnectivityState.READY)
    await asyncio.wait_for(mbd.event_ready.wait(), 0.100)
    assert mbd.connectivity_state == ConnectivityState.READY

    check_sent = list(zip(
        ['CONNECTING', 'CONNECTED', 'READY',],
        [next_address]*3))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

    tl.debug("Starting change of address while connected")
    third = '12:34:56:78:9a:bc'
    await mbd.change_address(third)
    assert not mbd.is_connected
    assert not mbd.is_released
    assert not mbd.is_captured
    assert not mbd.is_ready
    assert mbd.connectivity_state == ConnectivityState.INITIAL

    check_sent = list(zip(
        ['NOT_READY', 'DISCONNECTING', 'DISCONNECTING', 'DISCONNECTING',
         'DISCONNECTED', 'INITIAL'],
        [next_address] * 5 + [third]))
    await asyncio.sleep(0.100)
    assert mock_send_to_outbound_pipes.connectivity_sent == check_sent
    mock_send_to_outbound_pipes.connectivity_sent = []

