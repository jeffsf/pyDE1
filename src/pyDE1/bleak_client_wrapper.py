"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

The BlueZ stack will keep a connection to the device open even if Python exits.
This wrapper "automatically" adds an atexit close of the connection, as well as
trying to remove that atexit command if the object's __del__ method gets called.

There is only a handful of these at any one time. Using the atexit handler
with unique calls for each should be sufficient, rather than managing a list.
"""

import asyncio
import atexit
import logging

from typing import Union, Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice

logger = logging.getLogger('BCWrapper')


class BleakClientWrapped (BleakClient):
    """
    See also previous code in scale.py and de1.py

        def atexit_disconnect(self):
            def sync_disconnect():
    """
    def __init__(self, address_or_ble_device: Union[BLEDevice, str], **kwargs):
        super(BleakClientWrapped, self).__init__(
            address_or_ble_device=address_or_ble_device)
        self._willful_disconnect = False

    @property
    def name(self):
        try:
            retval = self._device_info['Name']
        except (KeyError, AttributeError, TypeError):
            # CoreBluetooth on bleak 0.11.0 and 0.12.0
            # TypeError if not connected
            retval = None
        return retval

    @property
    def willful_disconnect(self):
        return self._willful_disconnect


    def sync_disconnect(self):
        if not self.is_connected:
            logger.debug(
                f"atexit sync_disconnect: Not connected to {self.name} at "
                f"{self.address}")
            print(f"atexit sync_disconnect: Not connected to {self.name} at "
                f"{self.address}")
            return
        else:
            logger.info(
                f"atexit sync_disconnect: Disconnecting {self.name} at "
                f"{self.address}")
            print(f"atexit sync_disconnect: Disconnecting {self.name} at "
                f"{self.address}")
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                logger.info("atexit sync_disconnect: Starting event loop")
                print(f"atexit sync_disconnect: Starting event loop")
                loop.run_until_complete(self.disconnect())
            else:
                logger.info("atexit sync_disconnect: Using running loop")
                print(f"atexit sync_disconnect: Using running loop")
                loop.create_task(self.disconnect())
            # else:
            #     logger.critical(
            #         f"atexit sync_disconnect: NO LOOP AVAILABLE. "
            #         f"Unable to disconnect {self.name} at {self.address}"
            #     )
            #     print(f"atexit sync_disconnect: NO LOOP AVAILABLE. "
            #         f"Unable to disconnect {self.name} at {self.address}")

    async def connect(self, **kwargs) -> bool:
        atexit.register(self.sync_disconnect)
        retval = await super(BleakClientWrapped, self).connect(**kwargs)
        if retval:
            self._willful_disconnect = False
        return retval

    async def disconnect(self) -> bool:
        self._willful_disconnect = True
        retval = await super(BleakClientWrapped, self).disconnect()
        self._willful_disconnect = False
        if retval:
            logger.debug("Unregistering atexit disconnect "
                         f"{self.name} at {self.address}")
            atexit.unregister(self.sync_disconnect)
        return retval

    # TODO: How to handle unexpected disconnects?
    #       Handling auto-wrapping the on-disconnect handler seems excessive.

    # This is not the source of doubled disconnects
    # def __del__(self):
    #     if self.is_connected:
    #         logger.debug("__del__")
    #         self.sync_disconnect()


