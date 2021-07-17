"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

"Main" executable:
  * Set things up
  * Start and supervise processes
  * Manage aggregated logging
  * Manage top-level shutdown
"""

# Supervise:
#   Task: log_queue_reader_blocks
#   Processes: Controller, OutboundAPI, InboundAPI

import asyncio
import atexit
import logging
import multiprocessing
import os
import signal
import threading
import time

from pyDE1.api.outbound.mqtt import run_api_outbound
from pyDE1.api.inbound.http import run_api_inbound
from pyDE1.database.run import run_database_logger
from pyDE1.controller import run_controller

import pyDE1.default_logger

from pyDE1.supervise import SupervisedExecutor, SupervisedProcess

from pyDE1.signal_handlers import add_handler_sigchld_show_processes, \
    add_handler_shutdown_signals

from pyDE1.config.logging import LOG_DIRECTORY, LOG_FILENAME


def run():

    logger = logging.getLogger('run')

    # NB: Can only be set once, make sure the top-level script uses
    # if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    # If the controller is going to move into its own process
    # this process needs to handle the arrival of signals



    # Might be able to use SimpleQueue here,
    # at least until the queue gets joined at exit
    log_queue = multiprocessing.Queue()

    pyDE1.default_logger.initialize_default_logger(log_queue)
    pyDE1.default_logger.set_some_logging_levels()

    add_handler_sigchld_show_processes()

    async def graceful_shutdown(signal: signal.Signals,
                                loop: asyncio.AbstractEventLoop):

        supervised_inbound_api_process.do_not_restart = True
        supervised_outbound_api_process.do_not_restart = True
        supervised_controller_process.do_not_restart = True
        supervised_database_logger_process.do_not_restart = True

        t0 = time.time()
        logger = logging.getLogger('Shutdown')
        logger.info(f"{str(signal)} SHUTDOWN INITIATED "
                    f"{multiprocessing.active_children()}")
        logger.info("Terminate API processes")
        for p in multiprocessing.active_children():
            logger.info(f"Terminating {p}")
            p.terminate()
        logger.info("Waiting for processes to terminate")
        again = True
        while again:
            t1 = time.time()
            await asyncio.sleep(0.1)
            ac = multiprocessing.active_children()
            # logger.debug(ac)
            again = len(ac) > 0 and (t1 - t0 < 5)
            if not again:
                logger.info(f"Elapsed: {t1 - t0:0.3f} sec")
                if (t1 - t0 >= 5):
                    print(f"timed out with active_children {ac}")
                    for p in (ac):
                        try:
                            p.kill()
                        except AttributeError:
                            pass
        logger.info("Terminating logging")
        print("_terminate_logging.set()")
        _terminate_logging.set()
        print("loop.stop()")
        loop.stop()
        # print("loop.close()")
        # loop.close()

    add_handler_shutdown_signals(graceful_shutdown)

    @atexit.register
    def kill_stragglers():
        print("kill_stragglers()")
        procs = multiprocessing.active_children()
        for p in procs:
            print(f"Killing {p}")
            p.kill()
        print("buh-bye!")

    # These assume that the executor is threading
    _rotate_logfile = threading.Event()
    _terminate_logging = threading.Event()

    def request_logfile_rotation(sig, frame):
        logger.info("Request to rotate log received")
        _rotate_logfile.set()

    signal.signal(signal.SIGHUP, request_logfile_rotation)

    inbound_pipe_controller, inbound_pipe_server = multiprocessing.Pipe()

    # read, write, for simplex
    outbound_pipe_read, outbound_pipe_write = multiprocessing.Pipe(
        duplex=False)

    # MQTT API
    supervised_outbound_api_process = SupervisedProcess(
        target=run_api_outbound,
        kwargs={
            'log_queue': log_queue,
            'outbound_pipe': outbound_pipe_read,
        },
        name='OutboundAPI',
        daemon=False)
    supervised_outbound_api_process.start()

    # HTTP API
    supervised_inbound_api_process = SupervisedProcess(
        target=run_api_inbound,
        kwargs={
            'log_queue': log_queue,
            'api_pipe': inbound_pipe_server,
        },
        name='InboundAPI',
        daemon=False)
    supervised_inbound_api_process.start()

    # 20 packets per second, 20 seconds ~ 400
    database_queue = multiprocessing.Queue(maxsize=400)

    # Database logging
    supervised_database_logger_process = SupervisedProcess(
        target=run_database_logger,
        kwargs={
            'log_queue': log_queue,
            'notification_queue': database_queue,
        },
        name='DatabaseLogger',
        daemon=False)
    supervised_database_logger_process.start()

    # Core logic
    # TODO: Not clear how this should restart
    #       As the DE1 will need to be reinitialized
    supervised_controller_process = SupervisedProcess(
        target=run_controller,
        kwargs={
            'log_queue': log_queue,
            'inbound_pipe': inbound_pipe_controller,
            'outbound_pipe': outbound_pipe_write,
            'database_queue': database_queue,
        },
        name="Controller",
        daemon=False
    )
    supervised_controller_process.start()

    #
    # Now that the other processes are running, define the log handler
    # this will eventually get moved out
    #

    def log_queue_reader_blocks(log_queue: multiprocessing.Queue,
                                terminate_logging_event: threading.Event,
                                rotate_log_event: threading.Event):

        import email.utils

        if not os.path.exists(LOG_DIRECTORY):
            logger.error(
                "logfile_directory '{}' does not exist. Creating.".format(
                    os.path.realpath(LOG_DIRECTORY)
                )
            )
            # Will create intermediate directories
            # Will not use "mode" on intermediates
            os.makedirs(LOG_DIRECTORY)
        fq_logfile = os.path.join(LOG_DIRECTORY, LOG_FILENAME)
        while not terminate_logging_event.is_set():
            with open(file=fq_logfile, mode='a', buffering=1) as fh:
                logger.info(
                    f"Opening log file {email.utils.localtime().isoformat()}")
                while not terminate_logging_event.is_set():
                    record = log_queue.get()
                    # LogRecord is what gets enqueued
                    # TODO: Use QueueListener to further filter?
                    fh.write(record.msg + "\n")
                    try:
                        log_queue.task_done()
                    except AttributeError:
                        # multiprocessing.Queue() does not have .task_done()
                        pass

                    if rotate_log_event.is_set():
                        # TODO: Can this be formatted?
                        fh.write(f"Rotating log file\n")
                        fh.flush()
                        fh.close()
                        rotate_log_event.clear()
                        break

    # from pyDE1.watchdog import watchdog
    # SupervisedTask(watchdog)

    supervisor_lqr = SupervisedExecutor(None,
                                        log_queue_reader_blocks,
                                        log_queue,
                                        _terminate_logging,
                                        _rotate_logfile
                                        )

    loop.run_forever()

    print("after loop.run_forever()")
    # explicit TPE shutdown hangs
    # print("shutdown TPE")
    # logging_tpe.shutdown(cancel_futures=True)
    # print("after shutdown TPE")
    print(f"active_children: {multiprocessing.active_children()}")
    print("loop.close()")

    loop.close()

    # loop.close() seems to be the source of a kill-related exit code
    print("after loop.close()")


if __name__ == "__main__":
    run()