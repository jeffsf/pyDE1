"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import warnings
warnings.warn("try_de1.py is deprecated, run.py is an alternative",
              category=DeprecationWarning)

from pyDE1.run import run

if __name__ == '__main__':
    run()

