"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import atexit
import logging
import multiprocessing
import multiprocessing.connection as mpc
import signal
import time

from pyDE1.api.outbound.mqtt import run_api_outbound
from pyDE1.api.inbound.http import run_api_inbound

import pyDE1.default_logger

from pyDE1.controller import run_controller

if __name__ == "__main__":

    multiprocessing.set_start_method('spawn')

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    # If the controller is going to move into its own process
    # this process needs to handle the arrival of signals

    logger = logging.getLogger('Main')
    pyDE1.default_logger.initialize_default_logger()
    pyDE1.default_logger.set_some_logging_levels()

    async def signal_handler(signal: signal.Signals,
                             loop: asyncio.AbstractEventLoop):
        logger.info(f"{str(signal)} {multiprocessing.active_children()}")

    signals = (
        signal.SIGCHLD,
    )

    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda sig=sig: asyncio.create_task(signal_handler(sig, loop),
                                                name=str(sig)))

    async def bye_bye(signal: signal.Signals,
                      loop: asyncio.AbstractEventLoop):
        t0 = time.time()
        logger = logging.getLogger('MainShutdown')
        logger.info(f"{str(signal)} SHUTDOWN INITIATED "
                    f"{multiprocessing.active_children()}")
        # logger.info("Terminate API processes")
        # for p in multiprocessing.active_children():
        #     logger.info(f"Terminating {p}")
        #     p.terminate()
        logger.info("Waiting for processes to terminate")
        again = True
        while again:
            t1 = time.time()
            alive_in = inbound_api_process.is_alive()
            alive_out = outbound_api_process.is_alive()
            logger.info(ac := multiprocessing.active_children())
            await asyncio.sleep(0.1)
            again = len(ac) > 0 and (t1 - t0 < 5)
            if not again:
                logger.info(f"Elapsed: {t1 - t0:0.3f} sec")
                if (t1 - t0 >= 5):
                    for p in (ac):
                        try:
                            p.kill()
                        except AttributeError:
                            pass
        loop.stop()

    signals = (
        signal.SIGHUP,
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGTERM,
    )

    for sig in signals:
        loop.add_signal_handler(
            sig,
            lambda sig=sig: asyncio.create_task(
                bye_bye(sig, loop),
                name=str(sig)))

    outbound_api_queue = multiprocessing.Queue()
    inbound_api_queue = multiprocessing.Queue()

    inbound_pipe_controller, inbound_pipe_server \
        = multiprocessing.Pipe()

    # read, write, for simplex
    outbound_pipe_server, outbound_pipe_controller \
        = multiprocessing.Pipe(duplex=False)

    # MQTT API
    outbound_api_process = multiprocessing.Process(
        target=run_api_outbound,
        args=(outbound_pipe_server,),
        name='OutboundAPI',
        daemon=False)
    outbound_api_process.start()

    @atexit.register
    def terminate_outbound():
        outbound_api_process.terminate()

    # HTTP API
    inbound_api_process = multiprocessing.Process(
        target=run_api_inbound,
        args=(inbound_pipe_server,),
        name='InboundAPI',
        daemon=False)
    inbound_api_process.start()

    @atexit.register
    def terminate_inbound():
        inbound_api_process.terminate()

    # Core logic
    controller_process = multiprocessing.Process(
        target = run_controller,
        args=(
            inbound_pipe_controller,
            inbound_pipe_controller,
            outbound_pipe_controller,
        ),
        name="Controller",
        daemon=False
    )
    controller_process.start()

    # TODO: atexit should just iterate through child processes
    @atexit.register
    def terminate_controller():
        controller_process.terminate()


    loop.run_forever()

    # atexit not working with this form:
    # asyncio.run(run(), debug=True)
