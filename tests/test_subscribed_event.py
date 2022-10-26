"""
Copyright © 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import gc
import inspect
import logging
import time

from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock, PropertyMock, patch

import pytest
import pytest_asyncio

import pyDE1
import pyDE1.de1
from pyDE1.event_manager import SubscribedEvent, EventPayload

from tests.test_managed_bleak_device import mock_send_to_outbound_pipes

notify_logger = logging.getLogger('Notify')

def get_caller():
    call_info = notify_logger.findCaller(stacklevel=3)
    caller = f"{Path(call_info[0]).name}#{call_info[1]}:{call_info[2]}"
    return caller

def my_name():
    return notify_logger.findCaller(stacklevel=2)[2]

def plain_function(one_arg):
    notify_logger.info(
        f"{my_name()}({one_arg}) by {get_caller()}")

async def coro(one_arg):
    notify_logger.info(
        f"{my_name()}({one_arg}) by {get_caller()}")

async def coro_again(one_arg):
    notify_logger.info(
        f"{my_name()}({one_arg}) by {get_caller()}")

class SomeClass:

    def __init__(self):
        self.agf = self.return_another_generated_function()

    def bound_method_no_arg(self):
        notify_logger.info(
            f"{my_name()}({self}) by {get_caller()}")

    def bound_method_one_arg(self, one_arg):
        notify_logger.info(
            f"{my_name()}({self}, {one_arg}) by {get_caller()}")

    async def async_bound_method_no_arg(self):
        notify_logger.info(
            f"{my_name()}({self}) by {get_caller()}")

    async def async_bound_method_one_arg(self, one_arg):
        notify_logger.info(
            f"{my_name()}({self}, {one_arg}) by {get_caller()}")

    def return_generated_function(self):
        def generated_function(one_arg):
            notify_logger.info(
                f"{my_name()}({self}, {one_arg}) by {get_caller()}")

        return generated_function

    def return_async_generated_function(self):
        async def async_generated_function(one_arg):
            notify_logger.info(
                f"{my_name()}({self}, {one_arg}) by {get_caller()}")

        return async_generated_function

    def return_another_generated_function(self):
        def another_generated_function(one_arg):
            notify_logger.info(
                f"{my_name()}({self}, {one_arg}) by {get_caller()}")

        return another_generated_function


@pytest.mark.asyncio
async def test_funcs():
    val = 'some_string'
    some_obj = SomeClass()
    plain_function(val)
    await coro(val)
    some_obj.bound_method_no_arg()
    await some_obj.async_bound_method_no_arg()
    some_obj.bound_method_one_arg(val)
    await some_obj.async_bound_method_one_arg(val)

@pytest.mark.asyncio
async def test_subscribe():
    se = SubscribedEvent('test')
    some_obj = SomeClass()

    await se.subscribe(plain_function)
    await se.subscribe(coro)
    await se.subscribe(some_obj.bound_method_one_arg)
    await se.subscribe(some_obj.async_bound_method_one_arg)

    with pytest.raises(TypeError) as exec_info:
        await se.subscribe(some_obj.bound_method_no_arg)
        assert 'The callback must accept a single argument' in exec_info.value

    with pytest.raises(TypeError) as exec_info:
        await se.subscribe(some_obj.async_bound_method_no_arg)
        assert 'The callback must accept a single argument' in exec_info.value

@pytest.mark.asyncio
async def test_unsubscribe(mock_send_to_outbound_pipes,
                           caplog):
    se = SubscribedEvent('will render as the class str')
    # some_obj = SomeClass()
    mock_send_to_outbound_pipes.notify = True
    some_obj = SomeClass()

    ep = TestPayload(arrival_time=time.time(), text='test text')
    coro2 = coro
    id1 = await se.subscribe(coro)
    id2 = await se.subscribe(coro)
    id3 = await se.subscribe(coro_again)
    id4 = await se.subscribe(coro2)
    assert len(se._subscribers) == 4
    rv = await se.unsubscribe(id2)
    assert rv, "Expected True for success"
    assert len(se._subscribers) == 3
    rv = await se.unsubscribe('nope')
    assert not rv, "Expected False for non-existent subscriber"
    assert len(se._subscribers) == 3
    #
    await se.subscribe(some_obj.return_generated_function())
    await se.subscribe(some_obj.return_async_generated_function())
    assert len(se._subscribers) == 5


class TestPayload (EventPayload):

    def __init__(self, arrival_time: float, text: str):
        super(TestPayload, self).__init__(arrival_time=arrival_time)
        self.text = text


@pytest.mark.asyncio
async def test_publish(mock_send_to_outbound_pipes,
                       caplog):
    se = SubscribedEvent('will render as the class str')
    # some_obj = SomeClass()
    mock_send_to_outbound_pipes.notify = True

    ep = TestPayload(arrival_time=time.time(), text='test text')
    coro2 = coro
    await se.subscribe(coro)
    id = await se.subscribe(coro)
    await se.subscribe(coro_again)
    await se.subscribe(coro2)
    await se.unsubscribe(id)
    await se.publish(ep)
    await asyncio.sleep(0.100)
    called_list = []
    outbound_sent_count = 0
    for record in caplog.records:
        if record.name == 'Notify':
            called = record.message.split('(', maxsplit=1)[0]
            called_list.append(called)
        elif record.name == 'Notify.Outbound':
            outbound_sent_count += 1
    assert called_list == ['coro', 'coro_again', 'coro']
    assert outbound_sent_count == 1


@pytest.mark.asyncio
async def test_publish_new(mock_send_to_outbound_pipes,
                           caplog):
    se = SubscribedEvent('will render as the class str')
    some_obj = SomeClass()
    mock_send_to_outbound_pipes.notify = True

    ep = TestPayload(arrival_time=time.time(), text='test text')
    coro2 = coro
    await se.subscribe(coro)
    id1 = await se.subscribe(coro)
    await se.subscribe(coro_again)
    await se.subscribe(coro2)
    await se.subscribe(some_obj.async_bound_method_one_arg)
    await se.subscribe(plain_function)
    await se.subscribe(some_obj.bound_method_one_arg)
    # Try to replicate Scale failure mode (disappearing weakref target)
    await se.subscribe(some_obj.return_generated_function())
    await se.subscribe(some_obj.return_async_generated_function())
    hold_reference = some_obj.return_generated_function()
    await se.subscribe(hold_reference)
    await se.subscribe(some_obj.agf)
    await se.unsubscribe(id1)
    await se.publish(ep)
    await asyncio.sleep(0.100)
    called_list = []
    outbound_sent_count = 0
    warning_count = 0
    for record in caplog.records:
        if record.name == 'Notify':
            called = record.message.split('(', maxsplit=1)[0]
            called_list.append(called)
        elif record.name == 'Notify.Outbound':
            outbound_sent_count += 1
        elif (record.levelno == logging.WARNING
              and "using a hard reference" in record.message):
            warning_count += 1
    assert called_list == ['coro',
                           'coro_again',
                           'coro',
                           'async_bound_method_one_arg',
                           'plain_function',
                           'bound_method_one_arg',
                           'generated_function',
                           'async_generated_function',
                           'generated_function',
                           'another_generated_function'
                           ]
    assert outbound_sent_count == 1
    assert warning_count == 3

    caplog.clear()
    del some_obj
    gc.collect()
    await asyncio.sleep(0.100)
    await se.publish(ep)
    await asyncio.sleep(0.100)
    called_list = []
    outbound_sent_count = 0
    disappeared_count = 0
    for record in caplog.records:
        if record.name == 'Notify':
            called = record.message.split('(', maxsplit=1)[0]
            called_list.append(called)
        elif record.name == 'Notify.Outbound':
            outbound_sent_count += 1
        elif record.message.startswith(
                'Subscriber disappeared, unsubscribing SESubscriber'):
            disappeared_count += 1

    # TODO: It is not clear why the weakref-ed ones are still present
    EXPECT_GONE = False

    if EXPECT_GONE:
        assert called_list == ['coro',
                               'coro_again',
                               'coro',
                               # 'async_bound_method_one_arg',
                               'plain_function',
                               # 'bound_method_one_arg',
                               'generated_function',
                               'async_generated_function',
                               'generated_function',
                               # 'another_generated_function',
                               ]
        sub_list_len = 7
        expect_disappeared = 3
    else:
        assert called_list == ['coro',
                               'coro_again',
                               'coro',
                               'async_bound_method_one_arg',
                               'plain_function',
                               'bound_method_one_arg',
                               'generated_function',
                               'async_generated_function',
                               'generated_function',
                               'another_generated_function',
                               ]
        sub_list_len = 10
        expect_disappeared = 0
    assert outbound_sent_count == 1
    assert len(se._subscribers) == sub_list_len
    assert disappeared_count == expect_disappeared

    print()
    print(caplog.text)

