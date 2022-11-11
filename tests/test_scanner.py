"""
Copyright © 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import pytest

import bleak

@pytest.mark.asyncio
async def test_basic_scanner():
    # NB: Scanner.discover() is a class method, not an instance method
    # NB: Scanning starts when the context is entered
    #     Scanning will be stopped if running when the context is exited
    async with bleak.BleakScanner() as scanner:
        await asyncio.sleep(5)
        await scanner.stop()
        ddval = scanner.discovered_devices
        ddaad = scanner.discovered_devices_and_advertisement_data
        assert len(ddval) > 0, "This test needs discoverable devices"
        # print()
        # pprint.pprint(ddval)
        # print()
        # pprint.pprint(ddaad)
        # print()
        assert len(ddval) == len(ddaad)

