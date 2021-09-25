"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Main process for receiving update packets and logging to the database
"""

# Only import the minimal here, as it potentially ends up in all processes.
import multiprocessing
import multiprocessing.connection as mpc

# TODO: look into how loggers here relate to the root logger from "main"
import threading
from concurrent.futures import ThreadPoolExecutor

from pyDE1.database.write_notifications import read_queue_to_queue, record_data
from pyDE1.supervise import SupervisedExecutor

import pyDE1.config

def run_database_logger(config: pyDE1.config.Config,
                        log_queue: multiprocessing.Queue,
                        notification_queue: multiprocessing.Queue):

    import asyncio
    import logging
    import multiprocessing

    from pyDE1.supervise import SupervisedTask

    import pyDE1.shutdown_manager as sm

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    logger = logging.getLogger(multiprocessing.current_process().name)

    initialize_default_logger(log_queue)
    set_some_logging_levels()
    config.set_logging()

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    def on_shutdown_underway_cleanup():
        logger.info("Shutdown wait beginning")
        sm.shutdown_underway.wait()
        logger.info("Shutdown cleanup start")
        logger.info(f"Threads: {threading.enumerate()}")

        async def _the_rest():
            t = 1.1
            logger.info(f"Trying a {t} second sleep")
            await asyncio.sleep(t)
            logger.info(f"Threads: {threading.enumerate()}")
            logger.info("Setting cleanup_complete")
            sm.cleanup_complete.set()

        asyncio.run_coroutine_threadsafe(_the_rest(), loop)

    on_shutdown_wait_task = loop.run_in_executor(
        None, on_shutdown_underway_cleanup)

    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    loop.set_exception_handler(sm.exception_handler)

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            logger.debug("===== BRAP =====")

    SupervisedTask(heartbeat)

    SupervisedTask(record_data, notification_queue)

    loop.run_forever()