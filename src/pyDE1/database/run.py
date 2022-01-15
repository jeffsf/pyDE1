"""
Copyright © 2021, 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Main process for receiving update packets and logging to the database
"""

# Only import the minimal here, as it potentially ends up in all processes.

import multiprocessing

import pyDE1.config


def run_database_logger(master_config: pyDE1.config.Config,
                        log_queue: multiprocessing.Queue,
                        notification_queue: multiprocessing.Queue):

    pyDE1.config.config = master_config
    from pyDE1.config import config

    import asyncio
    import threading

    import pyDE1.pyde1_logging as pyde1_logging
    import pyDE1.shutdown_manager as sm

    # Failing if only here (and not at the module level)
    from pyDE1.database.write_notifications import record_data

    from pyDE1.supervise import SupervisedTask

    logger = pyDE1.getLogger('Database.Logger')

    pyde1_logging.setup_queue_logging(config.logging, log_queue)
    pyde1_logging.config_logger_levels(config.logging)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    def on_shutdown_underway_cleanup():
        logger.info("Watching for shutdown event")
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
        hlog = pyDE1.getLogger('Heartbeat.Database.Logger')
        while True:
            await asyncio.sleep(10)
            hlog.debug("===== BRAP =====")

    SupervisedTask(heartbeat)

    SupervisedTask(record_data, notification_queue)

    loop.run_forever()