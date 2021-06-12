"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

"Null" outbound processor that just keeps the queue clear,
counting the various messages by type,
logging every update_period seconds (and resetting the count)
"""

# Only import the minimal here, as it potentially ends up in all processes.\

import multiprocessing, multiprocessing.connection
import logging

# TODO: look into how loggers here relate to the root logger from "main"

# TODO: Look into or resolve processes' loggers writing over each other
import time


def run_api_outbound(api_outbound_queue: multiprocessing.Queue):
    logger = logging.getLogger('outbound')

    import asyncio
    import json

    async def run(api_outbound_queue: multiprocessing.Queue):

        last_update = time.time()
        update_period = 10  # in seconds
        counts = {}

        while True:
            item = api_outbound_queue.get()
            as_dict = json.loads(item)
            now = time.time()
            try:
                counts[as_dict['class']] += 1
            except KeyError:
                counts[as_dict['class']] = 1
            if now - last_update > update_period:
                logger.info(counts)
                counts = {}
                last_update = now

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(run(api_outbound_queue=api_outbound_queue))
