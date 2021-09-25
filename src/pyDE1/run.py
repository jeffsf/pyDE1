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
import logging.config
import logging.handlers
import multiprocessing
import os
import signal
import threading
import time
import traceback
import yaml

from types import FrameType

from pyDE1.api.outbound.mqtt import run_api_outbound
from pyDE1.api.inbound.http import run_api_inbound
from pyDE1.database.run import run_database_logger
from pyDE1.controller import run_controller

import pyDE1.default_logger

import pyDE1.shutdown_manager as sm

from pyDE1.supervise import SupervisedExecutor, SupervisedProcess

from pyDE1.config import config
from pyDE1.database.manage import check_schema


def run():

    logger = logging.getLogger('run')

    # NB: Can only be set once, make sure the top-level script uses
    # if __name__ == '__main__':
    #   Not enough if importing something that imports multiprocessing
    #   to avoid RuntimeError: context has already been set
    # TODO: Replace this rather ugly hack
    multiprocessing.set_start_method('spawn', force=True)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    # If the controller is going to move into its own process
    # this process needs to handle the arrival of signals

    # Might be able to use SimpleQueue here,
    # at least until the queue gets joined at exit
    log_queue = multiprocessing.Queue()

    pyDE1.default_logger.initialize_default_logger(log_queue)
    pyDE1.default_logger.set_some_logging_levels()
    config.set_logging()

    if not os.path.exists(config.logging.LOG_DIRECTORY):
        logger.error(
            "logfile_directory '{}' does not exist. Creating.".format(
                os.path.realpath(config.logging.LOG_DIRECTORY)
            )
        )
        # Will create intermediate directories
        # Will not use "mode" on intermediates
        os.makedirs(config.logging.LOG_DIRECTORY)

    fq_logfile = os.path.join(config.logging.LOG_DIRECTORY,
                              config.logging.LOG_FILENAME)

    log_file_handler = logging.handlers.WatchedFileHandler(fq_logfile)
    log_queue_listener = logging.handlers.QueueListener(log_queue,
                                                        log_file_handler)
    log_file_formatter = logging.Formatter(
        fmt=config.logging.FORMAT_MAIN
    )
    log_file_handler.setFormatter(log_file_formatter)

    log_queue_listener.start()

    def _sigchild_handler(signum: signal.Signals, frame: FrameType):
        ac = multiprocessing.active_children()
        logger.debug(
            f"Active children: {ac}")
        if sm.shutdown_underway.is_set() and len(ac) == 0:
            logger.debug("Setting cleanup_complete")
            sm.cleanup_complete.set()

    signal.signal(signal.SIGCHLD, _sigchild_handler)

    def on_shutdown_underway_cleanup():
        sm.shutdown_underway.wait()

        # This is intentional as the .do_not_restart setter
        # modifies the loop's readers
        def _the_rest_sync():
            logger.info("Setting do_not_restart")
            for sp in (
                    supervised_inbound_api_process,
                    supervised_outbound_api_process,
                    supervised_controller_process,
                    supervised_database_logger_process,
            ):
                sp.do_not_restart = True

            if sm.signal_rcvd is None:
                sig = signal.SIGTERM
            else:
                sig = sm.signal_rcvd
            for child in multiprocessing.active_children():
                # sp.terminate() would work, but pass the signal received
                logger.debug(f"os.kill {sig.name} {child.name}")
                os.kill(child.pid, sig)

        loop.call_soon_threadsafe(_the_rest_sync)

    on_shutdown_wait_task = loop.run_in_executor(
        None, on_shutdown_underway_cleanup)

    sm.attach_signal_handler_to_loop(sm.shutdown, loop)

    loop.set_exception_handler(sm.exception_handler)

    @atexit.register
    def kill_stragglers():
        procs = multiprocessing.active_children()
        if len(procs):
            print(f"kill {len(procs)} stragglers")
            for p in procs:
                print(f"Killing {p}")
                p.kill()
            print("buh-bye!")

    check_schema(loop)

    inbound_pipe_controller, inbound_pipe_server = multiprocessing.Pipe()

    # read, write, for simplex
    outbound_pipe_read, outbound_pipe_write = multiprocessing.Pipe(
        duplex=False)

    # MQTT API
    supervised_outbound_api_process = SupervisedProcess(
        target=run_api_outbound,
        kwargs={
            'config': config,
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
            'config': config,
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
            'config': config,
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
            'config': config,
            'log_queue': log_queue,
            'inbound_pipe': inbound_pipe_controller,
            'outbound_pipe': outbound_pipe_write,
            'database_queue': database_queue,
        },
        name="Controller",
        daemon=False
    )
    supervised_controller_process.start()

    loop.run_forever()

    logger.debug("After loop.run_forever()")
    # explicit TPE (thread pool executor) shutdown hangs
    # print("shutdown TPE")
    # logging_tpe.shutdown(cancel_futures=True)
    # print("after shutdown TPE")
    ac = multiprocessing.active_children()
    if len(ac):
        level = logging.ERROR
    else:
        level = logging.DEBUG
    logger.log(level, f"Active_children: {multiprocessing.active_children()}")

    # loop.close()
    #
    # # loop.close() seems to be the source of a kill-related exit code
    # logger.debug("After loop.close()")

    procs = multiprocessing.active_children()
    if len(procs):
        logger.error(f"Need to kill {len(procs)} stragglers")
        for p in procs:
            logger.warning(f"Killing {p}")
            p.kill()

    ev_str = ''
    try:
        ev_str = signal.Signals(-sm.exit_value).name
    except ValueError:
        if sm.exit_value == os.EX_SOFTWARE:
            ev_str = 'os.EX_SOFTWARE'

    logger.info(f"Will exit with {sm.exit_value} {ev_str}")
    log_queue_listener.stop()
    # Thread needs a bit to shut down
    # TODO: Can/should this thread be joined?
    time.sleep(1)
    exit(sm.exit_value)


if __name__ == "__main__":

    import argparse

    initial_log_config = """
---
version: 1
formatters:
    timestamped:
        class: logging.Formatter
        format: >-
            %(asctime)s %(levelname)s [%(processName)s]
            %(name)s: %(message)s
handlers:
    stderr:
        class: logging.StreamHandler
        formatter: timestamped
        level: DEBUG
root:
    handlers: [stderr]
    level: DEBUG
"""
    logging.config.dictConfig(yaml.safe_load(initial_log_config))

    ap = argparse.ArgumentParser(
        description="""Main executable to start the pyDE1 core.

        """
        f"Default configuration file is at {pyDE1.config.DEFAULT_CONFIG_FILE}"
    )
    ap.add_argument('-c', type=str, help='Use as alternate config file')
    ap.add_argument('--console', action='store_true',
                    help='Timestamped, DEBUG level on stderr logging')

    args = ap.parse_args()

    config.load_from_yaml(args.c)

    if args.console:
        config.logging.LEVEL_STDERR = logging.DEBUG
        config.logging.FORMAT_STDERR = \
            '%(asctime)s %(levelname)s [%(processName)s] %(name)s: %(message)s'

    run()
