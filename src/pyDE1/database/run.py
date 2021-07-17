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


def run_database_logger(log_queue: multiprocessing.Queue,
                        notification_queue: multiprocessing.Queue):

    import logging
    import multiprocessing
    import time
    import asyncio
    import json
    import signal

    from collections import Callable

    from pyDE1.utils import cancel_tasks_by_name
    from pyDE1.signal_handlers import add_handler_shutdown_signals, \
        process_shutdown_event

    from pyDE1.supervise import SupervisedTask

    from pyDE1.default_logger import initialize_default_logger, \
        set_some_logging_levels

    logger = logging.getLogger(multiprocessing.current_process().name)

    initialize_default_logger(log_queue)
    set_some_logging_levels()

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    async def shutdown_signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        logger = logging.getLogger('DBShutdown')
        if process_shutdown_event.is_set():
            logger.info(f"{str(signal)} Shutdown already underway")
            return
        process_shutdown_event.set()
        logger.info(f"{str(signal)} SHUTDOWN INITIATED")
        logger.info(f"Threads: {threading.enumerate()}")
        t = 1.1
        logger.info(f"Trying a {t} second sleep")
        await asyncio.sleep(t)
        logger.info("Shutting down asyncgens and default_executor")
        await asyncio.gather (
            loop.shutdown_asyncgens(),
            loop.shutdown_default_executor(),
        )
        logger.info("Shutting down other tasks")
        cancel_tasks_by_name('', starts_with=True)
        logger.info(f"Threads: {threading.enumerate()}")
        # Threads: [<_MainThread(MainThread, started 1993351184)>,
        # <Thread(QueueFeederThread, started daemon 1974527072)>,
        # <Connection(Thread-1, started 1964766304)>]
        #
        # Looks like the database thread isn't being cleaned up
        logger.info("Stopping loop")
        loop.stop()
        logger.info("Loop stopped, closing this process")
        # AttributeError: 'NoneType' object has no attribute 'kill'
        # multiprocessing.current_process().kill()
        multiprocessing.current_process().close()
        logger.info("Process closed")

    add_handler_shutdown_signals(shutdown_signal_handler)

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            logger.info("===== BRAP =====")

    SupervisedTask(heartbeat)

    SupervisedTask(record_data, notification_queue)

    loop.run_forever()