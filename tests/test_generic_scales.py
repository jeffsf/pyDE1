"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import logging
from asyncio import iscoroutinefunction

import pytest
from bleak import BLEDevice

import pyDE1
from pyDE1.de1.de1 import DE1
from pyDE1.dispatcher.resource import ConnectivityEnum
from pyDE1.event_manager.events import ConnectivityState, DeviceRole
from pyDE1.exceptions import DE1NotConnectedError, DE1UnsupportedDeviceError, \
    DE1RuntimeError

from pyDE1.scale.generic_scale import GenericScale, register_scale_class
from pyDE1.scale.atomax_skale_ii_gs import AtomaxSkaleII


@pytest.mark.asyncio
async def test_initialize_and_registration():

    not_connected_error = DE1NotConnectedError

    assert isinstance(pyDE1.scale.generic_scale._registered_scale_prefixes,
                      set)
    assert pyDE1.scale.generic_scale._prefix_to_class[''] == GenericScale

    gs: GenericScale = GenericScale()
    assert gs.address == ''
    assert gs.__class__.__name__ == 'GenericScale'
    assert gs.role == DeviceRole.SCALE
    assert gs.role.value == 'scale'
    assert gs.sensor_lag == 0.380
    assert gs.supports_button_press == False
    for prop in (
            'is_sending_weight_updates',
    ):
        with pytest.raises(not_connected_error):
            assert not getattr(gs, prop)
    for method_name in (
            'start_sending_weight_updates',
            'stop_sending_weight_updates',
            'start_sending_button_updates',
            'stop_sending_button_updates',
            'current_weight',
            'display_on',
            'display_off',
            'tare',
            'tare_with_bool',
    ):
        method = getattr(gs, method_name)
        with pytest.raises(not_connected_error):
            if iscoroutinefunction(method):
                await method()
            else:
                method()
    for b in (True, False,):
        with pytest.raises(not_connected_error):
            await gs.display_bool(b)
    standard_period = 0.100
    assert gs.estimated_period == standard_period
    assert gs.nominal_period == standard_period
    new_period = 0.123
    gs.nominal_period = new_period
    assert gs.nominal_period == new_period
    assert gs.estimated_period == new_period
    gs.nominal_period = standard_period
    assert gs.estimated_period == standard_period
    assert gs.nominal_period == standard_period

    assert not gs.is_connected
    assert not gs.is_captured
    assert not gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.INITIAL


def test_prefix_to_class(monkeypatch):

    @register_scale_class
    class AnotherScale (GenericScale):
        _supports_prefixes = ['Another', 'Sca']

    assert pyDE1.scale.generic_scale.prefix_to_class('') == GenericScale
    assert pyDE1.scale.generic_scale.prefix_to_class(None) == GenericScale
    assert pyDE1.scale.generic_scale.prefix_to_class('Another') == AnotherScale
    assert pyDE1.scale.generic_scale.prefix_to_class('Scale') == AnotherScale

    with pytest.raises(DE1UnsupportedDeviceError):
        pyDE1.scale.generic_scale.prefix_to_class('FAIL')

    with pytest.raises(DE1UnsupportedDeviceError):
        pyDE1.scale.generic_scale.prefix_to_class('ANOTHER')

    with pytest.raises(DE1UnsupportedDeviceError):
        pyDE1.scale.generic_scale.prefix_to_class('another')

    monkeypatch.setattr('pyDE1.scale.generic_scale._prefix_to_class', dict())

    with pytest.raises(DE1RuntimeError):
        pyDE1.scale.generic_scale.prefix_to_class('')


@pytest.mark.asyncio
async def test_simple_address_change():

    @register_scale_class
    class AnotherScale (GenericScale):
        _supports_prefixes = ['Another', 'Sca']

    gs: GenericScale = GenericScale()
    assert gs.address == ''
    assert gs.__class__.__name__ == 'GenericScale'
    assert gs.role == DeviceRole.SCALE

    addr1 = '11:22:33:44:55:66'
    await gs.change_address(addr1)

    assert gs.address == addr1

    assert not gs.is_connected
    assert not gs.is_captured
    assert not gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.INITIAL

    await gs.release()

    assert not gs.is_connected
    assert not gs.is_captured
    assert     gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.DISCONNECTED

    addr2 = '22:22:22:22:22:22'
    bled_gs = BLEDevice(address=addr2,
                        name='')
    await gs.change_address(bled_gs)
    assert gs.address == addr2

    assert not gs.is_connected
    assert not gs.is_captured
    assert not gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.INITIAL

    addr3 = '33:33:33:33:33:33'
    bled_fail = BLEDevice(address=addr3,
                          name='FAIL')
    with pytest.raises(DE1UnsupportedDeviceError):
        await gs.change_address(bled_fail)

    bled_none = BLEDevice(address=addr3,
                          name=None)
    await gs.change_address(bled_none)
    assert gs.address == addr3

    assert not gs.is_connected
    assert not gs.is_captured
    assert not gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.INITIAL

    addr4 = '44:44:44:44:44:44'
    bled_4 = BLEDevice(address=addr4,
                          name='Another')
    await gs.change_address(bled_4)
    assert gs.address == addr4
    assert type(gs) == AnotherScale

    assert not gs.is_connected
    assert not gs.is_captured
    assert not gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.INITIAL

    await gs.change_address(None)
    assert gs.address == ''
    assert type(gs) == GenericScale

    assert not gs.is_connected
    assert not gs.is_captured
    assert not gs.is_released
    assert not gs.is_ready

    assert gs.connectivity == ConnectivityEnum.NOT_CONNECTED
    assert gs.connectivity_state == ConnectivityState.INITIAL

@pytest.mark.skip
@pytest.mark.live
@pytest.mark.asyncio
async def test_skaleII_connect(caplog):

    caplog.set_level(logging.INFO)

    addr = 'FF:06:AF:6B:64:D6'

    gs = GenericScale()
    assert gs.name == 'GenericScale: (unknown)'
    await gs.change_address(addr)
    await gs.capture()
    assert gs.address == addr
    assert gs.name == 'AtomaxSkaleII: Skale'
    assert type(gs) == AtomaxSkaleII

    # TODO: Finalizer to clean up BlueZ connection seems needed
    await gs.change_address(None)
    assert not gs.is_connected
    assert type(gs) == GenericScale
    assert gs.name == 'GenericScale: (unknown)'

    await asyncio.sleep(0.100)

    print()
    print(caplog.text)