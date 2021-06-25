"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import logging
import os
import time
import multiprocessing


def set_some_logging_levels():
    logging.getLogger(multiprocessing.current_process().name).info(
        "Setting asyncio and bleak logging to INFO"
    )
    logging.getLogger('asyncio').setLevel(logging.INFO)
    logging.getLogger('bleak').setLevel(logging.INFO)


def initialize_default_logger():

    format_string = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logfile_directory = '_logs'

    logging.basicConfig(level=logging.DEBUG,
                        format=format_string,
                        )

    # It looks like steerr handler comes with "basicConfig"
    #     root.handlers = [<StreamHandler <stderr> (NOTSET)>]

    # Define console logging
    # console = logging.StreamHandler()
    # console.setLevel(logging.DEBUG)
    # formatter = logging.Formatter(format_string)
    # console.setFormatter(formatter)

    # Add console logging to root logger
    # logging.getLogger('').addHandler(console)

    # Trim down the "noise" from asyncio and bleak.backends.bluezdbus.client

    logger = logging.getLogger(multiprocessing.current_process().name)

    lf_name = time.strftime('default.%Y-%m-%d_%H%M%S.log', time.localtime())
    lf_name = os.path.join(logfile_directory, lf_name)
    if not os.path.exists(logfile_directory):
        logger.error(
            "logfile_directory '{}' does not exist. Creating.".format(
                os.path.realpath(logfile_directory)
            )
        )
        os.mkdir(logfile_directory)
    try:
        lf = logging.FileHandler(lf_name)
    except FileNotFoundError:
        logger.critical(
            f"Unable to open {os.path.realpath(lf_name)}"
        )
        raise
    lf.setFormatter(logging.Formatter(format_string))
    lf.setLevel(logging.DEBUG)
    logging.getLogger('').addHandler(lf)
    logger.info(f"Logging PID {os.getpid()} to {os.path.realpath(lf_name)}")
