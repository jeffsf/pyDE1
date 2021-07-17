"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import multiprocessing
import logging
import signal
import threading
from types import FrameType
from typing import Callable, Coroutine

# process-global indication of shutdown intent
process_shutdown_event = threading.Event()

SHUTDOWN_SIGNALS = (
        # signal.SIGHUP,  # reserved for log rotation
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGTERM,
    )


def add_handler_shutdown_signals(async_graceful_shutdown: Callable[
    [signal.Signals, asyncio.AbstractEventLoop], Coroutine]):
    # No loop is running yet
    loop = asyncio.get_event_loop()
    for sig in SHUTDOWN_SIGNALS:
        loop.add_signal_handler(
            sig,
            lambda sig=sig: asyncio.create_task(
                async_graceful_shutdown(sig, loop),
                name=str(sig)))


def add_handler_sigchld_show_processes():

    logger = logging.getLogger('signal.SIGCHLD')

    def _show_processes(signum: signal.Signals, frame: FrameType):
        logger.debug(
            f"Active children: {multiprocessing.active_children()}")

    signal.signal(signal.SIGCHLD, _show_processes)

