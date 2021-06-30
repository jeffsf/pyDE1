"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

from pyDE1.de1 import DE1


# TODO: Decide how best to implement and add to DE1 singleton directly.

class Feature:

    def __init__(self):
        self._de1 = DE1()

    # TODO: Manage cache of firmware version and GHC presence
    #       * Load when received
    #       * Clear on disconnect

    # TODO: What should "unknown" return?

    @property
    def ghc(self):
        return None

    @property
    def skip_to_next(self):
        # FW version >= ????
        return None

    @property
    def read_through_unimplemented_mmr(self):
        """
        Will not hang if read attempted on
            MMR0x80LowAddr.GHC_PREFERRED_INTERFACE,
            MMR0x80LowAddr.MAXIMUM_PRESSURE,
        See also MMR0x80LowAddr.will_hang(addr_low, mmr_req_len)
        FW 1260, no
        """
        return False

