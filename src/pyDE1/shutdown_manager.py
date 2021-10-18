"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Somewhat generic signal and exception handlers for "graceful" shutdown.

App exit will be -signal_number or os_EX_SOFTWARE on exception handled here.

See further:
    https://docs.python.org/3/library/asyncio-eventloop.html
       #asyncio.loop.set_exception_handler
    https://www.roguelynn.com/words/asyncio-exception-handling/


Example cleanup routine:

async def wait_then_cleanup(client: mqtt.Client):
    await loop.run_in_executor(None, shutdown_underway.wait)
    client.disconnect()
    client.loop_stop()
    cleanup_complete.set()

"""
import asyncio
import logging
import multiprocessing
import os
import pprint
import signal
import traceback
from typing import Callable, Optional, Coroutine, Iterable, Union

import pyDE1

# Set when a shutdown is requested
# Does not start a shutdown when set
shutdown_underway = multiprocessing.Event()

# Should be set by app-specific clean-up routines
cleanup_complete = multiprocessing.Event()

# Give up on waiting for cleanup_complete.is_set() after
CLEANUP_WAIT = 5.0  # seconds

exit_value = os.EX_OK
signal_rcvd = None

logger = pyDE1.getLogger('Shutdown')

default_signal_set = (
    signal.SIGHUP,
    signal.SIGINT,
    signal.SIGQUIT,
    signal.SIGABRT,
    signal.SIGTERM,
)


def task_to_string(t: asyncio.Task):
    return f"{t.get_name()}: {t.get_coro().cr_frame.f_code}"


def exception_handler(loop: asyncio.AbstractEventLoop,
                      context: dict):
    if shutdown_underway.is_set():
        level = logging.WARNING
    else:
        level = logging.CRITICAL
    exc_class = context['exception'].__class__
    logger.log(level,
        f"Uncaught exception (loop) {exc_class}:\n"
        f"{pprint.pformat(context)}")
    if not shutdown_underway.is_set():
        loop.create_task(shutdown(None, loop))


async def shutdown(sig: Optional[signal.Signals],
                   loop: asyncio.AbstractEventLoop):
    global exit_value
    global signal_rcvd
    signal_rcvd = sig

    if shutdown_underway.is_set():
        if sig is not None:
            name_str = f"from {sig.name}"
        else:
            name_str = " (no signal passed)"
        logger.info(f"Already shutting down, ignoring {name_str}")
        return

    shutdown_underway.set() # Cleanup should trigger off this
    graceful = (sig == signal.SIGTERM)

    if graceful: # The "expected" shutdown signal
        logger.info(f"Shutting down from {sig.name}")
    elif sig is None:
        # Can happen if called due to an uncaught exception
        logger.critical(
            "Shutdown called without signal (likely an uncaught exception)")
    else:
        logger.critical(f"Shutdown called due to {sig.name}")

    logger.info(f"Waiting up to {CLEANUP_WAIT} seconds for clean up.")
    signaled = await loop.run_in_executor(None,
                                          cleanup_complete.wait, CLEANUP_WAIT)
    if signaled:
        logger.info("cleanup_complete set, continuing")
    else:
        logger.error("cleanup_complete not set fast enough, continuing")

    # Thread exit requires a flag that is periodically checked
    # it is nearly impossible to "kill" a thread
    logger.info("Shutting down default executor")
    await loop.shutdown_default_executor()
    logger.info("Shutting down asyncgens")
    await loop.shutdown_asyncgens()

    me = asyncio.current_task(loop)
    tasks_to_cancel = [t for t in asyncio.all_tasks(loop)
                       if t is not me]
    logger.info(f"Cancelling {len(tasks_to_cancel)} running tasks")
    for t in tasks_to_cancel:
        logger.info(f"Cancelling {task_to_string(t)}")
        try:
            t.cancel("Shutdown underway")
        except asyncio.exceptions.CancelledError:
            pass
    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    logger.info("Stopping asyncio loop")

    loop.stop()
    # .close() here raises RuntimeError('Cannot close a running event loop')
    # logger.info("Closing loop")
    # loop.close()
    if graceful:
        exit_value = os.EX_OK
    elif sig:
        exit_value = -sig.value
    else:
        exit_value = os.EX_SOFTWARE


def attach_signal_handler_to_loop(signal_handler: Callable[
                        [signal.Signals, asyncio.AbstractEventLoop], Coroutine],
                                  loop: asyncio.AbstractEventLoop,
                                  signals: Optional[Union[
                                      Iterable[signal.Signals],
                                      signal.Signals]] = default_signal_set):

    if isinstance(signals, signal.Signals):
        signals = (signals,)

    # See https://www.roguelynn.com/words/asyncio-graceful-shutdowns/
    #     https://docs.python-guide.org/writing/gotchas/#late-binding-closures
    # for why sig needs to be bound in the lambda
    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(signal_handler(s, loop))
        )


# Usually also needed:
#       loop.set_exception_handler(exception_handler)

# Useful as a callback on tasks
def shutdown_if_exception(fut: asyncio.Future):
    if fut.exception():
        tbe = traceback.TracebackException.from_exception(fut.exception())
        if shutdown_underway.is_set():
            level = logging.WARNING
        else:
            level = logging.CRITICAL
        logger.log(level,
                   "Uncaught exception (future): " + ''.join(tbe.format()))
        if not shutdown_underway.is_set():
            logger.critical("Initiating shutdown")
            loop = asyncio.get_running_loop()
            loop.create_task(shutdown(None, loop))



