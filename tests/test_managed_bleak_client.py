"""
Copyright © 2021-2023 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import logging
import time
from typing import Optional

import bleak
import pytest

from unittest.mock import MagicMock, AsyncMock, PropertyMock, patch

from bleak.backends.client import BaseBleakClient, \
    get_platform_client_backend_type

from pyDE1.bledev.managed_bleak_client import (
    CaptureRequest, ManagedBleakClient, cq_from_code, cq_to_code
)
from pyDE1.exceptions import DE1NoAddressError


def print_all_codes():
    for c in 'CRN':
        for t in 'CR':
            for p in 'NCRX':
                print(f"    '{c+p+t}': '',")
        print("    #")
    for c in 'CRN':
        for t in 'N':
            for p in 'NCRX':
                # print(f"    '{c+p+t}': '',")
                print(f"    '{c+p+t}': '{c+p+t}',")


vectors_maybe_initiate_action_normalize = {
    # key: present queue, value: resulting queue
    # action_taken = key[1] != value[1]
    #
    'CNC': 'CNC',
    'CCC': 'CXC',
    'CRC': 'CXC',
    'CXC': 'CXC',
    #
    'CNR': 'CRR',
    'CCR': 'CXR',
    'CRR': 'CRR',
    'CXR': 'CXR',
    #
    'RNC': 'RCC',
    'RCC': 'RCC',
    'RRC': 'RXC',
    'RXC': 'RXC',
    #
    'RNR': 'RNR',
    'RCR': 'RXR',
    'RRR': 'RXR',
    'RXR': 'RXR',
    #
    'NNC': 'NCC',
    'NCC': 'NCC',
    'NRC': 'NXC',
    'NXC': 'NXC',
    #
    'NNR': 'NRR',
    'NCR': 'NXR',
    'NRR': 'NRR',
    'NXR': 'NXR',
    #
    'CNN': 'CNN',
    'CCN': 'CCN',
    'CRN': 'CRN',
    'CXN': 'CXN',
    'RNN': 'RNN',
    'RCN': 'RCN',
    'RRN': 'RRN',
    'RXN': 'RXN',
    'NNN': 'NNN',
    'NCN': 'NCN',
    'NRN': 'NRN',
    'NXN': 'NXN',
}


@pytest.mark.asyncio
async def test_maybe_initiate_action_normalize():
    with patch('pyDE1.bledev.managed_bleak_client.ManagedBleakClient'
               '._start_request_with_lock',
               new_callable=MagicMock) as mock_start_request:
        for iq, eq in vectors_maybe_initiate_action_normalize.items():
            initial_queue = cq_from_code(iq)
            expected_queue = cq_from_code(eq)
            mbc = ManagedBleakClient('')
            assert mbc.address == ''
            mbc._capture_queue = initial_queue
            req = mbc._capture_queue.target
            async with mbc._capture_queue_lock:
                mbc._maybe_initiate_action_have_lock(request=req)
            assert mbc._capture_queue == expected_queue, \
                f"Unexpected resulting queue from {initial_queue} with {req}"


@pytest.mark.asyncio
async def test_maybe_initiate_action_with_no_arg():
    with patch('pyDE1.bledev.managed_bleak_client.ManagedBleakClient'
               '._start_request_with_lock',
               new_callable=MagicMock) as mock_start_request:
        for iq, eq in vectors_maybe_initiate_action_normalize.items():
            initial_queue = cq_from_code(iq)
            expected_queue = cq_from_code(eq)
            mbc = ManagedBleakClient(None)
            assert mbc.address == '', "Using None as address should return ''"
            mbc._capture_queue = initial_queue
            async with mbc._capture_queue_lock:
                mbc._maybe_initiate_action_have_lock()
            assert mbc._capture_queue == expected_queue, \
                f"Unexpected resulting queue from {initial_queue} with {'()'}"


@pytest.mark.asyncio
async def test_maybe_initiate_action_with_none_arg():
    with patch('pyDE1.bledev.managed_bleak_client.ManagedBleakClient'
               '._start_request_with_lock',
               new_callable=MagicMock) as mock_start_request:
        for iq, eq in vectors_maybe_initiate_action_normalize.items():
            initial_queue = cq_from_code(iq)
            expected_queue = cq_from_code(eq)
            mbc = ManagedBleakClient('No address')
            mbc._capture_queue = initial_queue
            async with mbc._capture_queue_lock:
                mbc._maybe_initiate_action_have_lock(request=None)
            assert mbc._capture_queue == expected_queue, \
                f"Unexpected resulting queue from {initial_queue} with {None}"


vectors_maybe_initiate_action_capture = {
    # key: present queue, value: resulting queue
    # action_taken = key[1] != value[1]
    #
    'CNC': 'CNC',
    'CCC': 'CXC',
    'CRC': 'CXC',
    'CXC': 'CXC',
    #
    'CNR': 'CNC',
    'CCR': 'CXC',
    'CRR': 'CXC',
    'CXR': 'CXC',
    #
    'RNC': 'RCC',
    'RCC': 'RCC',
    'RRC': 'RXC',
    'RXC': 'RXC',
    #
    'RNR': 'RCC',
    'RCR': 'RCC',
    'RRR': 'RXC',
    'RXR': 'RXC',
    #
    'NNC': 'NCC',
    'NCC': 'NCC',
    'NRC': 'NXC',
    'NXC': 'NXC',
    #
    'NNR': 'NCC',
    'NCR': 'NCC',
    'NRR': 'NXC',
    'NXR': 'NXC',
    #
    'CNN': 'CNC',
    'CCN': 'CXC',
    'CRN': 'CXC',
    'CXN': 'CXC',
    'RNN': 'RCC',
    'RCN': 'RCC',
    'RRN': 'RXC',
    'RXN': 'RXC',
    'NNN': 'NCC',
    'NCN': 'NCC',
    'NRN': 'NXC',
    'NXN': 'NXC',
}


@pytest.mark.asyncio
async def test_maybe_initiate_action_capture():
    with patch('pyDE1.bledev.managed_bleak_client.ManagedBleakClient'
               '._start_request_with_lock',
               new_callable=MagicMock) as mock_start_request:
        for iq, eq in vectors_maybe_initiate_action_capture.items():
            initial_queue = cq_from_code(iq)
            expected_queue = cq_from_code(eq)
            mbc = ManagedBleakClient('No address')
            mbc._capture_queue = initial_queue
            req = CaptureRequest.CAPTURE
            async with mbc._capture_queue_lock:
                mbc._maybe_initiate_action_have_lock(request=req)
            assert mbc._capture_queue == expected_queue, \
                f"Unexpected resulting queue from {initial_queue} with {req}"


vectors_maybe_initiate_action_release = {
    # key: present queue, value: resulting queue
    # action_taken = key[1] != value[1]
    #
    'CNC': 'CRR',
    'CCC': 'CXR',
    'CRC': 'CRR',
    'CXC': 'CXR',
    #
    'CNR': 'CRR',
    'CCR': 'CXR',
    'CRR': 'CRR',
    'CXR': 'CXR',
    #
    'RNC': 'RNR',
    'RCC': 'RXR',
    'RRC': 'RXR',
    'RXC': 'RXR',
    #
    'RNR': 'RNR',
    'RCR': 'RXR',
    'RRR': 'RXR',
    'RXR': 'RXR',
    #
    'NNC': 'NRR',
    'NCC': 'NXR',
    'NRC': 'NRR',
    'NXC': 'NXR',
    #
    'NNR': 'NRR',
    'NCR': 'NXR',
    'NRR': 'NRR',
    'NXR': 'NXR',
    #
    'CNN': 'CRR',
    'CCN': 'CXR',
    'CRN': 'CRR',
    'CXN': 'CXR',
    'RNN': 'RNR',
    'RCN': 'RXR',
    'RRN': 'RXR',
    'RXN': 'RXR',
    'NNN': 'NRR',
    'NCN': 'NXR',
    'NRN': 'NRR',
    'NXN': 'NXR',
}


@pytest.mark.asyncio
async def test_maybe_initiate_action_release():
    with patch('pyDE1.bledev.managed_bleak_client.ManagedBleakClient'
               '._start_request_with_lock',
               new_callable=MagicMock) as mock_start_request:
        for iq, eq in vectors_maybe_initiate_action_release.items():
            initial_queue = cq_from_code(iq)
            expected_queue = cq_from_code(eq)
            mbc = ManagedBleakClient('No address')
            mbc._capture_queue = initial_queue
            req = CaptureRequest.RELEASE
            async with mbc._capture_queue_lock:
                mbc._maybe_initiate_action_have_lock(request=req)
            assert mbc._capture_queue == expected_queue, \
                f"Unexpected resulting queue from {initial_queue} with {req}"


@pytest.mark.asyncio
async def test_confirm_capture_then_release_requests():
    mbc = ManagedBleakClient('No address')
    await mbc.request_capture()
    assert mbc._capture_queue == cq_from_code('NCC')
    await mbc.request_release()
    assert mbc._capture_queue == cq_from_code('NXR')


@pytest.mark.asyncio
async def test_done_callback_call_sequence():
    mbc = ManagedBleakClient('No address')
    event = asyncio.Event()
    async def sleepy():
        await event.wait()
    t = asyncio.create_task(sleepy())
    t.add_done_callback(mbc._capture_release_done_callback)
    mbc._pending_task = t
    assert mbc._pending_task is not None, f"Before event: {mbc._pending_task}"
    event.set()
    await asyncio.sleep(0.100)
    assert mbc._pending_task is None


@pytest.mark.asyncio
async def test_property_mock():
    with patch(f"{backend_class_str}.is_connected",
               new_callable=PropertyMock) as mock_is_connected:
        rv = True  # Simple value passed by value
        mock_is_connected.return_value = rv
        mbc = ManagedBleakClient('No address')
        assert mbc.is_connected is True
        rv = 'New'
        assert mbc.is_connected != 'New'
        mock_is_connected.return_value = "Modified"
        assert mbc.is_connected == 'Modified'
    mbcic = mbc.is_connected
    assert (
            (isinstance(mbcic, BaseBleakClient._DeprecatedIsConnectedReturn)
             and not mbcic)
        or mbcic is False
    ), "Returns wrapper _DeprecatedIsConnectedReturn at least through v0.18.1"


def test_retry_delay():
    """
    Checks internal logic, does not check assigned parameters
    """
    mbc = ManagedBleakClient('No address')

    mbc._retry_start_initial_delay = 10
    mbc._retry_initial_delay = 11
    mbc._retry_start_long_delay = 20
    mbc._retry_long_delay = 22

    mbc._retry_since = None
    assert mbc._retry_delay() == 0

    mbc._retry_since = time.time()
    assert mbc._retry_delay() == 0

    mbc._retry_since = time.time() - 1
    assert mbc._retry_delay() == 0

    mbc._retry_since = time.time() - 12
    assert mbc._retry_delay() == 11

    mbc._retry_since = time.time() - 21
    assert mbc._retry_delay() == 22


async def check_retry_delay(client: ManagedBleakClient,
                            retry_delay: Optional[float]):
    two_minutes = 120  # A somewhat arbitrary amount of time
    an_hour = 7200   # An even more arbitrary amount of time

    async with client._capture_queue_lock:

        cq = client._capture_queue

        assert not (
                retry_delay is None
                and client._capture_queue.pending
                is CaptureRequest.CAPTURE), \
            "None is not a valid retry_delay for CAPTURE"

        if (p := client._capture_queue.pending) is not CaptureRequest.CAPTURE:
            assert not client._retry_wait_event.is_set(), \
                f"{p}: Expected wait event not set {cq}"
            assert client._retry_wait_task is None, \
                f"{p}: Expected no wait task {cq}"
            assert client._retry_since is None, \
                f"{p}: Expected _retry_since is None {cq}"
            assert not client._retry_is_active, \
                f"{p}: Expected _retry_is_active to be False {cq}"

        else:  # CaptureRequest.CAPTURE pending from here on

            assert client._retry_since is not None, \
                f"Active: Expected there is started time {cq}"
            assert client._retry_is_active, \
                f"Active: Expected _retry_is_active {cq}"

            if retry_delay == 0:
                ds = 'Zero delay'
                assert client._retry_wait_event.is_set(), \
                    f"{ds}: Expected wait event is set {cq}"
                assert client._retry_wait_task is None, \
                    f"{ds}: Expected no wait task {cq}"

            else:
                ds = f"Delay of {retry_delay}"
                assert not client._retry_wait_event.is_set(), \
                    f"{ds}: Expected wait event is not set {cq}"
                assert client._retry_wait_task is not None, \
                    f"{ds}: Expected there is a wait task {cq}"




# Will need to mock the backend, but it is dynamically determined
# Remember to patch the disconnected_callback call

PBC = get_platform_client_backend_type()
backend_class_str = f"{PBC.__module__}.{PBC.__qualname__}"

@pytest.mark.asyncio
async def test_connect_sequence():
    with \
            patch(f"{backend_class_str}.is_connected",
               new_callable=PropertyMock) as mock_is_connected, \
            patch(f"{backend_class_str}.connect",
                  new_callable=AsyncMock) as mock_connect, \
            patch(f"{backend_class_str}.disconnect",
                  new_callable=AsyncMock) as mock_disconnect:

        mock_is_connected.return_value = False
        turnstile_connect = asyncio.Event()
        turnstile_disconnect = asyncio.Event()

        logger=logging.getLogger('test_connect_sequence')

        async def mock_connect_side_effect(**kwargs):
            try:
                await turnstile_connect.wait()
                turnstile_connect.clear()
            except Exception:
                turnstile_connect.clear()
                raise
            logger.warning('Setting is_connected = True')
            mock_is_connected.return_value = True
            return True  # As with the original backend implementation

        async def mock_disconnect_side_effect():
            try:
                await turnstile_disconnect.wait()
                turnstile_disconnect.clear()
            except Exception:
                turnstile_disconnect.clear()
                raise
            # TODO: Is this backend agnostic?
            if mbc._backend._disconnected_callback is not None:
                mbc._backend._disconnected_callback(mbc)
            logger.warning('Setting is_connected = False')
            mock_is_connected.return_value = False
            return True  # As with the original backend implementation

        mock_connect.side_effect = mock_connect_side_effect
        mock_disconnect.side_effect = mock_disconnect_side_effect

        loop = asyncio.get_running_loop()

        mbc = ManagedBleakClient('No address')

        mbc.test_underway = 'Fresh'
        assert not mbc.is_connected
        assert not mbc.is_captured
        assert not mbc.is_released, 'Before first capture, not is_released'
        assert mbc._capture_queue == cq_from_code('NNN')
        assert mbc.event_no_pending.is_set()
        assert not mbc.connectivity_task_pending
        await check_retry_delay(mbc, None)

        # Release from fresh

        mbc.test_underway = 'Release from fresh'
        assert mbc._retry_wait_task is None
        loop.call_later(0.1, turnstile_disconnect.set)
        await asyncio.wait_for(mbc.release(), 10)
        assert not mbc.is_connected
        assert not mbc.is_captured
        assert mbc.is_released
        assert mbc._capture_queue == cq_from_code('RNR')
        assert mbc.event_no_pending.is_set()
        assert not mbc.connectivity_task_pending
        await check_retry_delay(mbc, None)
        assert mock_is_connected.return_value is False

        # Capture from release

        mbc.test_underway = 'Capture'
        loop.call_later(0.1, turnstile_connect.set)
        await asyncio.wait_for(mbc.capture(), 10)
        assert mbc.is_connected
        assert mbc.is_captured
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('CNC')
        assert mbc.event_no_pending.is_set()
        assert not mbc.connectivity_task_pending
        await check_retry_delay(mbc, None)

        # Now cause a disconnect and confirm that it reconnects

        mbc.test_underway = 'Disconnect "forced" from captured'
        assert mbc._retry_wait_task is None
        turnstile_disconnect.set()
        # turnstile_connect.set()
        await mbc._backend.disconnect()
        await asyncio.sleep(0.100)
        assert not mbc.is_connected
        assert not mbc.is_captured
        # As pending, not "released" yet
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('RCC')
        assert not mbc.event_no_pending.is_set()
        assert mbc.connectivity_task_pending
        await check_retry_delay(mbc, 0)

        # wait for reconnect

        mbc.test_underway = 'Expect capture after disconnect'
        turnstile_connect.set()
        await asyncio.sleep(0.100)
        assert mbc.is_connected
        assert mbc.is_captured
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('CNC')
        assert mbc.event_no_pending.is_set()
        assert not mbc.connectivity_task_pending
        await check_retry_delay(mbc, None)

        # Now release from captured

        mbc.test_underway = 'Release'
        turnstile_connect.set()
        turnstile_disconnect.set()
        await mbc.release()
        await asyncio.sleep(0.100)
        assert not mbc.is_connected
        assert not mbc.is_captured
        assert mbc.is_released
        assert mbc._capture_queue == cq_from_code('RNR')
        assert mbc.event_no_pending.is_set()
        assert not mbc.connectivity_task_pending
        await check_retry_delay(mbc, None)

        turnstile_connect.set()
        turnstile_disconnect.set()
        await asyncio.sleep(0.100)
        assert not mbc.is_connected
        assert not mbc.is_captured
        assert mbc.is_released
        assert mbc._capture_queue == cq_from_code('RNR')
        assert mbc.event_no_pending.is_set()
        assert not mbc.connectivity_task_pending
        await check_retry_delay(mbc, None)


@pytest.mark.asyncio
async def test_connect_sequence_with_retry(monkeypatch):

    target_class = bleak.get_platform_client_backend_type()

    mock_is_connected = None

    turnstile_connect = asyncio.Event()
    do_connect = True

    turnstile_disconnect = asyncio.Event()


    task_completed_event = asyncio.Event()

    async def mock_connect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_connect.wait()
            turnstile_connect.clear()
            if do_connect:
                mock_is_connected = True
        except asyncio.CancelledError:
            turnstile_connect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class,'connect',
                        mock_connect)

    async def mock_disconnect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_disconnect.wait()
            turnstile_disconnect.clear()
            if mbc._backend._disconnected_callback is not None:
                mbc._backend._disconnected_callback(mbc)
            mock_is_connected = False
        except asyncio.CancelledError:
            turnstile_disconnect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class,'disconnect',
                        mock_disconnect)

    def mock_is_connected_getter(*args, **kwargs):
        nonlocal mock_is_connected
        return mock_is_connected

    monkeypatch.setattr(target_class, 'is_connected',
                        property(fget=mock_is_connected_getter))

    # Done patching

    loop = asyncio.get_running_loop()

    mbc = ManagedBleakClient('No address')

    # Wrap the generated done callback

    _original_cr_done_cb = mbc._capture_release_done_callback

    def _cr_done_cb_wrapper(*args, **kwargs):
        task_completed_event.set()
        _original_cr_done_cb(*args, **kwargs)

    mbc._capture_release_done_callback = _cr_done_cb_wrapper


    test_underway = 'Fresh'
    assert not mbc.is_connected
    assert not mbc.is_captured
    assert not mbc.is_released, 'Before first capture, not is_released'
    assert mbc._capture_queue == cq_from_code('NNN')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)

    # Release from fresh

    test_underway = 'Release from fresh'
    assert mbc._retry_wait_task is None
    loop.call_later(0.1, turnstile_disconnect.set)
    await mbc.request_release()
    try:
        await asyncio.wait_for(task_completed_event.wait(), 2)
    except TimeoutError:
        raise
    task_completed_event.clear()
    assert not mbc.is_connected
    assert not mbc.is_captured
    assert mbc.is_released
    assert mbc._capture_queue == cq_from_code('RNR')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)
    assert mock_is_connected is False

    # Capture from release

    test_underway = 'Capture fail'
    do_connect = False
    await mbc.request_capture()
    for cnt in range(0, 5):
        loop.call_later(0.1, turnstile_connect.set)
        try:
            await asyncio.wait_for(task_completed_event.wait(), 2)
        except TimeoutError:
            raise
        task_completed_event.clear()
        assert not mbc.is_connected
        assert not mbc.is_captured
        # As pending, not "released" yet
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('RCC')
        assert not mbc.event_no_pending.is_set()
        assert mbc.connectivity_task_pending
        await check_retry_delay(mbc, 0)
    do_connect = True
    loop.call_later(0.1, turnstile_connect.set)
    try:
        await asyncio.wait_for(task_completed_event.wait(), 2)
    except TimeoutError:
        raise
    task_completed_event.clear()
    assert mbc.is_connected
    assert mbc.is_captured
    assert not mbc.is_released
    assert mbc._capture_queue == cq_from_code('CNC')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)


@pytest.mark.asyncio
async def test_retry_fallback(monkeypatch):

    target_class = bleak.get_platform_client_backend_type()

    mock_is_connected = None

    turnstile_connect = asyncio.Event()
    do_connect = True

    turnstile_disconnect = asyncio.Event()

    task_completed_event = asyncio.Event()

    async def mock_connect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_connect.wait()
            turnstile_connect.clear()
            if do_connect:
                mock_is_connected = True
        except asyncio.CancelledError:
            turnstile_connect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class,
                        'connect',
                        mock_connect)

    async def mock_disconnect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_disconnect.wait()
            turnstile_disconnect.clear()
            if mbc._backend._disconnected_callback is not None:
                mbc._backend._disconnected_callback(mbc)
            mock_is_connected = False
        except asyncio.CancelledError:
            turnstile_disconnect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'disconnect',
                        mock_disconnect)

    def mock_is_connected_getter(*args, **kwargs):
        nonlocal mock_is_connected
        return mock_is_connected

    monkeypatch.setattr(target_class, 'is_connected',
                        property(fget=mock_is_connected_getter))

    # Done patching

    mock_cb = MagicMock()
    mock_cb.__name__ = 'mock_cb'

    loop = asyncio.get_running_loop()

    mbc = ManagedBleakClient('No address',
                             on_change_callback=mock_cb)

    # Wrap the generated done callback

    _original_cr_done_cb = mbc._capture_release_done_callback

    def _cr_done_cb_wrapper(*args, **kwargs):
        task_completed_event.set()
        _original_cr_done_cb(*args, **kwargs)

    mbc._capture_release_done_callback = _cr_done_cb_wrapper

    # Adjust the fall-back times

    initial_delay = 0.3
    long_delay = 0.4

    mbc._retry_initial_delay = initial_delay
    mbc._retry_long_delay = long_delay

    test_underway = 'Fresh'
    assert not mbc.is_connected
    assert not mbc.is_captured
    assert not mbc.is_released, 'Before first capture, not is_released'
    assert mbc._capture_queue == cq_from_code('NNN')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)

    # Release from fresh

    test_underway = 'Release from fresh'
    assert mbc._retry_wait_task is None
    loop.call_later(0.1, turnstile_disconnect.set)
    await mbc.request_release()
    try:
        await asyncio.wait_for(task_completed_event.wait(), 2)
    except TimeoutError:
        raise
    task_completed_event.clear()
    assert not mbc.is_connected
    assert not mbc.is_captured
    assert mbc.is_released
    assert mbc._capture_queue == cq_from_code('RNR')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)
    assert mock_is_connected is False

    # Capture from release

    test_underway = 'Capture fail'
    do_connect = False
    t0 = time.time()
    await mbc.request_capture()
    await asyncio.sleep(0.100)
    assert mbc._pending_task is not None
    assert mbc._retry_since is not None
    t_since = mbc._retry_since
    assert mbc._retry_since > t0

    test_underway = 'Capture fail: no delay'
    for cnt in range(0, 2):
        assert mbc._retry_since == t_since
        assert not mbc._retry_delay()
        loop.call_later(0.1, turnstile_connect.set)
        try:
            await asyncio.wait_for(task_completed_event.wait(), 2)
        except TimeoutError:
            raise
        task_completed_event.clear()
        assert not mbc.is_connected
        assert not mbc.is_captured
        # As pending, not "released" yet
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('RCC')
        assert not mbc.event_no_pending.is_set()
        assert mbc.connectivity_task_pending
        await check_retry_delay(mbc, 0)

    test_underway = 'Capture fail: initial delay'
    mbc._retry_since = time.time() - mbc._retry_start_initial_delay
    for cnt in range(0, 2):
        assert mbc._retry_delay() == initial_delay
        loop.call_later(0.1, turnstile_connect.set)
        try:
            await asyncio.wait_for(task_completed_event.wait(), 2)
        except TimeoutError:
            pass
        task_completed_event.clear()
        assert not mbc.is_connected
        assert not mbc.is_captured
        # As pending, not "released" yet
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('RCC')
        assert not mbc.event_no_pending.is_set()
        assert mbc.connectivity_task_pending
        await check_retry_delay(mbc, mbc._retry_initial_delay)

    test_underway = 'Capture fail: long delay'
    mbc._retry_since = time.time() - mbc._retry_start_long_delay
    for cnt in range(0, 2):
        assert mbc._retry_delay() == long_delay
        loop.call_later(0.1, turnstile_connect.set)
        try:
            await asyncio.wait_for(task_completed_event.wait(), 2)
        except TimeoutError:
            pass
        task_completed_event.clear()
        assert not mbc.is_connected
        assert not mbc.is_captured
        # As pending, not "released" yet
        assert not mbc.is_released
        assert mbc._capture_queue == cq_from_code('RCC')
        assert not mbc.event_no_pending.is_set()
        assert mbc.connectivity_task_pending
        await check_retry_delay(
            mbc, mbc._retry_long_delay if cnt else mbc._retry_initial_delay)

    test_underway = 'Capture fail: allow connect'
    do_connect = True
    loop.call_later(0.1, turnstile_connect.set)
    try:
        await asyncio.wait_for(task_completed_event.wait(), 2)
    except TimeoutError:
        raise
    task_completed_event.clear()
    assert mbc.is_connected
    assert mbc.is_captured
    assert not mbc.is_released
    assert mbc._capture_queue == cq_from_code('CNC')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)

    # This is completely bogus
    # assert mock_cb.call_count == 18
    check_against = ['NNN',
                     'NNN', 'NRR', 'RRR', 'RXR', 'RNR',
                     'RCC', 'RNC', 'RCC', 'RNC', 'RCC',
                     'RNC', 'RCC', 'RNC', 'RCC', 'RNC',
                     'RCC', 'RNC', 'RCC', 'CNC']
    assert mock_cb_to_checklist(mock_cb) == check_against


def mock_cb_to_checklist(mcb: MagicMock) -> list:
    """
    For a mock called with (any, previous: CaptureQueue, new: CaptureQueue)
    returns a list of the CaptureQueue "codes"
    including the original value and then each new value
    """
    retval = [cq_to_code(mcb.call_args_list[0].args[1])]
    for ca in mcb.call_args_list:
        retval.append(cq_to_code(ca.args[2]))
    return retval


def assert_captured(client: ManagedBleakClient):
    assert client._backend.is_connected
    assert client.is_connected
    assert client.is_captured
    assert not client.is_released
    assert client._capture_queue == cq_from_code('CNC')
    assert client.event_no_pending.is_set()
    assert not client.connectivity_task_pending


def assert_released(client: ManagedBleakClient):
    assert not client._backend.is_connected
    assert not client.is_connected
    assert not client.is_captured
    assert client.is_released
    assert client._capture_queue == cq_from_code('RNR')
    assert client.event_no_pending.is_set()
    assert not client.connectivity_task_pending

def assert_initial(client: ManagedBleakClient):
    assert not client._backend.is_connected
    assert not client.is_connected
    assert not client.is_captured
    assert not client.is_released
    assert client._capture_queue == cq_from_code('NNN')
    assert client.event_no_pending.is_set()
    assert not client.connectivity_task_pending
    assert client._retry_since is None
    assert not client._retry_wait_event.is_set()


@pytest.mark.asyncio
async def test_legacy_disconnected_callback(monkeypatch):

    target_class = bleak.get_platform_client_backend_type()

    mock_is_connected = None

    turnstile_connect = asyncio.Event()
    do_connect = True

    turnstile_disconnect = asyncio.Event()

    task_completed_event = asyncio.Event()

    async def mock_connect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_connect.wait()
            turnstile_connect.clear()
            if do_connect:
                mock_is_connected = True
        except asyncio.CancelledError:
            turnstile_connect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'connect',
                        mock_connect)

    async def mock_disconnect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_disconnect.wait()
            turnstile_disconnect.clear()
            if mbc._backend._disconnected_callback is not None:
                mbc._backend._disconnected_callback(mbc)
            mock_is_connected = False
        except asyncio.CancelledError:
            turnstile_disconnect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'disconnect',
                        mock_disconnect)

    def mock_is_connected_getter(*args, **kwargs):
        nonlocal mock_is_connected
        return mock_is_connected

    monkeypatch.setattr(target_class, 'is_connected',
                        property(fget=mock_is_connected_getter))

    dcb_mock0 = MagicMock()
    dcb_mock1 = MagicMock()

    # Done patching

    loop = asyncio.get_running_loop()

    mbc = ManagedBleakClient('No address',
                             disconnected_callback=dcb_mock0)

    test_underway = 'Fresh'
    dcb_mock0.assert_not_called()
    assert not mbc.is_connected
    assert not mbc.is_captured
    assert not mbc.is_released, 'Before first capture, not is_released'
    assert mbc._capture_queue == cq_from_code('NNN')
    assert mbc.event_no_pending.is_set()
    assert not mbc.connectivity_task_pending
    await check_retry_delay(mbc, None)
    dcb_mock0.assert_not_called()

    # Release from fresh

    test_underway = 'Release from fresh'
    assert not mbc._backend.is_connected
    assert mbc._retry_wait_task is None
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.request_release()
    try:
        await asyncio.wait_for(mbc.event_released.wait(), 2)
    except TimeoutError:
        raise
    assert_released(mbc)
    assert mbc._legacy_disconnected_callback == dcb_mock0

    # TODO: Why is disconnected_callback being called here?
    # Bleak behavior should be that disconnected_callback
    # is only called if the connectivity has changed
    dcb_mock0.assert_called()

    assert dcb_mock0.call_count == 1
    dcb_mock0.reset_mock()
    dcb_mock0.assert_not_called()

    # Capture

    test_underway = 'Capture from released'
    assert_released(mbc)
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.request_capture()
    try:
        await asyncio.wait_for(mbc.event_captured.wait(), 2)
    except TimeoutError:
        raise
    assert_captured(mbc)
    assert mbc._legacy_disconnected_callback == dcb_mock0

    dcb_mock0.assert_not_called()

    test_underway = 'Unexpected disconnect'
    turnstile_disconnect.set()
    turnstile_connect.clear()
    await mbc._backend.disconnect()
    await asyncio.sleep(0.100)
    dcb_mock0.assert_called_once()

    dcb_mock0.reset_mock()

    test_underway = 'Wait for recapture'
    assert not mbc._backend.is_connected
    assert mbc._retry_wait_task is None
    turnstile_disconnect.set()
    turnstile_connect.set()
    try:
        await asyncio.wait_for(mbc.event_captured.wait(), 2)
    except TimeoutError:
        raise
    assert_captured(mbc)
    assert mbc._legacy_disconnected_callback == dcb_mock0

    dcb_mock0.assert_not_called()

    test_underway = 'Intentional disconnect'
    assert_captured(mbc)
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.request_release()
    try:
        await asyncio.wait_for(mbc.event_released.wait(), 2)
    except TimeoutError:
        raise
    assert_released(mbc)
    assert mbc._legacy_disconnected_callback == dcb_mock0
    dcb_mock0.assert_called_once()
    dcb_mock0.reset_mock()

    test_underway = 'Recapture 2'
    assert_released(mbc)
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.capture(2)
    assert_captured(mbc)
    dcb_mock0.assert_not_called()

    test_underway = 'Change callback'
    # Expect FutureWarning: This method will be removed future version,
    # pass the callback to the ManagedBleakClient constructor instead.
    mbc.set_disconnected_callback(dcb_mock1)
    assert mbc._legacy_disconnected_callback != dcb_mock0
    assert mbc._legacy_disconnected_callback == dcb_mock1

    test_underway = 'Intentional disconnect 2'
    assert_captured(mbc)
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.release()
    await asyncio.wait_for(mbc.event_no_pending.wait(), 0.1)
    assert_released(mbc)
    assert mbc._legacy_disconnected_callback == dcb_mock1
    dcb_mock1.assert_called_once()


@pytest.mark.asyncio
async def test_address_change(monkeypatch, caplog):

    target_class = bleak.get_platform_client_backend_type()

    mock_is_connected = None

    turnstile_connect = asyncio.Event()
    do_connect = True

    turnstile_disconnect = asyncio.Event()

    async def mock_connect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_connect.wait()
            turnstile_connect.clear()
            if do_connect:
                mock_is_connected = True
        except asyncio.CancelledError:
            turnstile_connect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'connect',
                        mock_connect)

    async def mock_disconnect(*args, **kwargs):
        nonlocal mock_is_connected
        try:
            await turnstile_disconnect.wait()
            turnstile_disconnect.clear()
            if mbc._backend._disconnected_callback is not None:
                mbc._backend._disconnected_callback(mbc)
            mock_is_connected = False
        except asyncio.CancelledError:
            turnstile_disconnect.clear()
        return True  # As with the original backend implementation

    monkeypatch.setattr(target_class, 'disconnect',
                        mock_disconnect)

    def mock_is_connected_getter(*args, **kwargs):
        nonlocal mock_is_connected
        return mock_is_connected

    monkeypatch.setattr(target_class, 'is_connected',
                        property(fget=mock_is_connected_getter))

    # Done patching

    loop = asyncio.get_running_loop()

    mbc = ManagedBleakClient('No address')

    test_underway = 'Fresh'
    assert_initial(mbc)
    assert mbc.address == 'No address'

    # Capture from fresh

    test_underway = 'Capture'
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.request_capture()
    await asyncio.wait_for(mbc.event_captured.wait(), 2)
    assert_captured(mbc)

    # Confirm that the address and the backend does not change
    # if the new address is the same as the old

    old_address = mbc.address
    old_backend = mbc._backend
    old_backend_address = mbc._backend.address

    # Confirm that same address doesn't change things

    caplog.set_level(logging.INFO)
    test_underway = 'No change'
    await mbc.change_address('No address')
    assert_captured(mbc)
    assert mbc.address == old_address
    assert mbc._backend == old_backend
    assert mbc._backend.address == old_backend_address

    # Confirm that changing the address does change things
    # and reset to "fresh" state

    test_underway = 'With change'
    await mbc.change_address('New value')
    assert_initial(mbc)
    assert mbc.address == 'New value'
    assert mbc._backend != old_backend
    assert mbc._backend.address == 'New value'

    # Capture from fresh

    test_underway = 'Capture again'
    turnstile_disconnect.set()
    turnstile_connect.set()
    await mbc.request_capture()
    await asyncio.wait_for(mbc.event_captured.wait(), 2)
    assert_captured(mbc)

@pytest.mark.skip
@pytest.mark.live
@pytest.mark.slow
@pytest.mark.asyncio
async def test_delayed_reconnect():

    mbc = ManagedBleakClient('')
    await mbc.change_address('FF:06:AF:6B:64:D6')
    assert not mbc._backend._services_resolved
    await mbc.capture()
    await asyncio.sleep(1)
    await mbc.release()
    await asyncio.sleep(30)
    await mbc.capture()
    assert mbc.is_captured

@pytest.mark.asyncio
async def test_fail_connect_with_no_address():
    mbc = ManagedBleakClient('')
    with pytest.raises(DE1NoAddressError):
        await mbc.request_capture()
