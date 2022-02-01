"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import collections
import json

"""
Logging Objectives:

  * The location and verbosity of the log file can be easily configured

  * The log file contains enough information to be useful to understand
    how the action progressed and why something might have gone wrong
    
  * The output to stderr, when run as a service, is meaningful to confirm
    that the service has started properly, as well as to capture any
    run-time errors
    
  * The output to stderr cam be easily configured for interactive debugging,
    including timestamps (omitted when running as a service, as they are 
    timestamped by systemd or the system logging system) and increasing
    verbosity as needed
    
  * The logging verbosity of the pyDE1 code can be adjusted, as needed,
    on a fine-grained basis
    
  * The logging verbosity of third-party libraries can be adjusted, as needed
  
  * Log-entry sequence is preserved no matter from which process it originates
  
  * Consistent initialization and configuration across processes


Python logging has a few quirks:
  
  * Entry of a log message to the logging system is gated by the effective
    level of the logger. That may be a level set on the logger itself,
    or, if none is set, traversing upwards through the parents until
    one with a level explicitly set is found. 
    
  * Exit of a log message that is in the system already is determined by
    the level set on the handler (not that of the logger to which it is 
    attached). When using a QueueListener, it needs to be instantiated with
    respect_handler_level=True for this behavior to occur.
    
  * LogRecord does not need to be formatted by the QueueHandler,
    it can be formatted by the "delivery" handler
    
  * dictConfig() apparently can't manage the QueueListener's handlers directly
  
  * Calling the module-level logging.info() or the like implicitly calls
      if len(root.handlers) == 0:
        basicConfig()
  
High-Level Design:

  * Immediately initialize a stderr-based logger that can be used until
    configuration can be read and parsed, then the "real" logging structures 
    created and configured
    
  * All delivery is through handlers on a QueueListener
    * Runs in the main process
      * First process up, hopefully the last down
      * The main process doesn't do much else
    * The QueueListener and its handlers are available in this module
      (for the main process, they are None here in other processes)
    * By setting the formatter and level on the handler (or filters, or ...)
      the output can be controlled from what input was let into the system

  * Leave the root logger with only a "plain" QueueHandler
    * This blocks inadvertent calls to logging.basicConfig()
    
  * Move all pYDE1-related logging to be children of 'pyde1' (WIP)
    * This allows setting to DEBUG for effective-level inheritance
      without setting third-party packages' effective level
      
  * Use a separate logging config file that will allow setting of 
    specific logging levels on the logger, to control entry into 
    the logging system. The separate file can be dropped in 
    without changing the general config file. By using dictConfig(), 
    it should be possible to configure the loggers' levels, 
    pyde1 or third-party, without having to enumerate them in advance.
    
    
Note: Can't 'from import pyDE1.config import config' 
      as may not be the right config if not pyDE1 "main"
"""

# Get all instantiated loggers: logging.root.manager.loggerDict

import copy
import logging
import multiprocessing
import multiprocessing.connection as mpc
import os
import warnings
from logging.handlers import QueueHandler, MemoryHandler
from typing import Optional, Union

import pyDE1
from pyDE1.config_load import ConfigLoadable


def setup_initial_logger():
    """
    Configure a basic logger that logs to stderr at DEBUG level
    sufficient to report errors in reading config and then
    starting the "real" logger.

    Capture the records in a MemoryHandler for later flushing
    to the logfile_handler, when it becomes available
    """
    CAPACITY = 1000  # records

    global memory_handler

    formatter = Formatter(
        "%(asctime)s %(levelname)s [%(processName)s] %(name)s: %(message)s")

    initial_handler = logging.StreamHandler()
    initial_handler.setFormatter(formatter)
    initial_handler.setLevel(logging.DEBUG)
    initial_handler.name = 'initial_logger'

    memory_handler = MemoryHandlerMulti(
        capacity=CAPACITY,
        flushLevel=(logging.CRITICAL + 1),
        target = None,
        flushOnClose=True
    )
    memory_handler.name = 'memory_handler'

    root_logger = logging.getLogger()
    if len(rlh := root_logger.handlers):
        root_logger.warning(
            f"setup_initial_logger found exising handlers {rlh}, removing"
        )
        for handler in rlh:
            root_logger.removeHandler(handler)
    root_logger.addHandler(initial_handler)
    root_logger.addHandler(memory_handler)
    root_logger.setLevel(logging.DEBUG)


class Formatter (logging.Formatter):
    """
    Change the logger name on output to remove _ROOT_LOGGER_PREFIX = 'pyDE1'
    and add 'root.' to others
    """

    # Same init, just override the format calls that reference the name

    @classmethod
    def revised_record(cls, record: logging.LogRecord) -> logging.LogRecord:
        revised = copy.copy(record)
        name = revised.name
        if name.startswith(pyDE1._ROOT_LOGGER_PREFIX):
            revised.name = name[pyDE1._ROOT_LOGGER_PREFIX_LEN:]
        elif name == 'root':
            pass
        else:
            revised.name = 'root.' + name
        return revised

    def format(self, record: logging.LogRecord) -> str:
        return super(Formatter, self).format(
            self.revised_record(record))

    # Don't override both, or record gets converted twice
    # def formatMessage(self, record: logging.LogRecord) -> str:
    #     return super(Formatter, self).formatMessage(
    #         self.revised_record(record))


# Common definition of the 'logging' section of config

class ConfigLogging (ConfigLoadable):
    def __init__(self):
        self.LOG_DIRECTORY = '/var/log/pyde1/'
        # NB: The log file name is matched against [a-zA-Z0-9._-]
        self.LOG_FILENAME = None    # Needs to be overridden
        self.formatters = ConfigLoggingFormatters()
        self.handlers = ConfigLoggingHandlers()
        self.LOGGERS = {
            'root.aiosqlite':   'INFO',
            'root.asyncio':     'INFO',
            'root.bleak':       'INFO',
        }


class ConfigLoggingFormatters (ConfigLoadable):
    def __init__(self):
        self.STYLE = '%'
        self.LOGFILE = '%(asctime)s ' \
                       '%(levelname)s [%(processName)s] %(name)s: %(message)s'
        self.MQTT = self.LOGFILE
        self.STDERR  = '%(levelname)s [%(processName)s] %(name)s: %(message)s'


class ConfigLoggingHandlers (ConfigLoadable):
    def __init__(self):
        self.LOGFILE = 'INFO'
        self.MQTT  = 'ERROR'
        self.STDERR  = 'WARNING'


# In a module, unfortunately,
#     thing = property(thing_getter, thing_setter)
# just accesses the property object, rather than providing property behavior

log_queue_listener = None
memory_handler = None
stderr_handler = None
mqtt_handler = None
logfile_handler = None


def setup_queue_and_listener(config_logging: ConfigLogging, 
                             log_queue: multiprocessing.Queue,
                             mqtt_connection: mpc.Connection):
    """
    Call only from the process that will be doing the logging

    NB: Call *after* config has been read
    :param config_logging: 
    """
    _setup_logging_internal(config_logging,
                            log_queue=log_queue,
                            mqtt_connection=mqtt_connection)


def setup_direct_logging(config_logging: ConfigLogging):
    """
    Intended for single-process applications, such as Visualizer uploader
    
    NB: Call *after* config has been read
    :param config_logging: 
    """
    if multiprocessing.parent_process() is not None \
            or len(multiprocessing.active_children()) != 0:
        warnings.warn(
            "setup_direct_logging() called in a multiprocessing environment",
            RuntimeWarning
        )
    _setup_logging_internal(config_logging,
                            log_queue=None,
                            mqtt_connection=None)


def _setup_logging_internal(config_logging: ConfigLogging,
                            log_queue: Optional[multiprocessing.Queue],
                            mqtt_connection: Optional[mpc.Connection]):
    """
    If log_queue is present, set up queue and listener
    If None, set up direct logging
    :param config_logging: 
    """
    global log_queue_listener, \
        memory_handler, stderr_handler, mqtt_handler, logfile_handler

    # log_queue = multiprocessing.Queue()

    root_logger = logging.getLogger()

    stderr_handler = logging.StreamHandler()
    stderr_formatter = Formatter(fmt=config_logging.formatters.STDERR)
    stderr_handler.setFormatter(stderr_formatter)
    stderr_handler.setLevel(config_logging.handlers.STDERR)
    stderr_handler.name = 'stderr_handler'

    root_logger.info(
        f"Configured stderr_handler: {stderr_handler}")

    if mqtt_connection:
        mqtt_handler = PipeHandler(pipe_connection=mqtt_connection)
        mqtt_formatter = Formatter(fmt=config_logging.formatters.MQTT)
        mqtt_handler.setFormatter(mqtt_formatter)
        mqtt_handler.setLevel(config_logging.handlers.MQTT)
    else:
        mqtt_handler = logging.NullHandler()
    mqtt_handler.name = 'mqtt_handler'

    root_logger.info(
        f"Configured mqtt_handler: {mqtt_handler}")

    if not os.path.exists(config_logging.LOG_DIRECTORY):
        root_logger.error(
            "logfile_directory '{}' does not exist. Creating.".format(
                os.path.realpath(config_logging.LOG_DIRECTORY)
            )
        )
        # Will create intermediate directories
        # Does not use "mode" on intermediates
        os.makedirs(config_logging.LOG_DIRECTORY)

    if config_logging.LOG_DIRECTORY is None \
            or config_logging.LOG_FILENAME is None:
        logfile_handler = logging.NullHandler()
        root_logger.warning(
            "File logging disabled as either "
            "LOG_DIRECTORY or LOG_FILENAME is None "
            f"'{config_logging.LOG_DIRECTORY}' '{config_logging.LOG_FILENAME}'")
    else:
        fq_logfile = os.path.join(config_logging.LOG_DIRECTORY,
                                  config_logging.LOG_FILENAME)
        logfile_handler = logging.handlers.WatchedFileHandler(fq_logfile)

    logfile_formatter = Formatter(fmt=config_logging.formatters.LOGFILE)
    logfile_handler.setFormatter(logfile_formatter)
    logfile_handler.setLevel(config_logging.handlers.LOGFILE)
    logfile_handler.name = 'logfile_handler'

    root_logger.info(
        f"Configured logfile_handler: {logfile_handler}")

    if log_queue is not None:

        log_queue_listener = logging.handlers.QueueListener(
            log_queue,
            stderr_handler,
            mqtt_handler,
            logfile_handler,
            respect_handler_level=True
        )
        log_queue_listener.start()
    
        root_logger.info(f"Started {log_queue_listener}")
        root_logger.debug(
            f"log_queue_listener handlers: {log_queue_listener.handlers}")

    else:
        
        for handler in root_logger.handlers:
            root_logger.removeHandler(handler)
        root_logger.addHandler(stderr_handler)
        # TODO: Is there a use case and meaningful way to add the mqtt_handler?
        # root_logger.addHandler(mqtt_handler)
        root_logger.addHandler(logfile_handler)

    if memory_handler:
        root_logger.removeHandler(memory_handler)
        memory_handler.target = (logfile_handler, mqtt_handler)
        memory_handler.close()
        memory_handler = None

    set_root_logger_levels(config_logging)


def get_int_from_level(logging_level: Union[int, str]):
    if isinstance(logging_level, str):
        # Despite the name, this will return a number from a string
        return logging.getLevelName(logging_level)
    else:
        return logging_level


def set_root_logger_levels(config_logging: ConfigLogging):
    # No easy way to "DRY" this that I can think of today
    try:
        level_stderr = stderr_handler.level
    except AttributeError:
        level_stderr = get_int_from_level(config_logging.handlers.STDERR)
    try:
        level_mqtt = mqtt_handler.level
    except AttributeError:
        level_mqtt = get_int_from_level(config_logging.handlers.STDERR)
    try:
        level_logfile = logfile_handler.level
    except AttributeError:
        level_logfile = get_int_from_level(config_logging.handlers.LOGFILE)
    level = min(level_logfile, level_mqtt, level_stderr)
    pyDE1.getLogger().setLevel(level)
    pyDE1.getLogger('root').setLevel(level)


def setup_queue_logging(config_logging: ConfigLogging,
                        queue: multiprocessing.Queue):
    """
    Convert root logger to just using a QueueHandler(queue) for everything

    It should be the case that only third-party logging is inheriting
    the root logger's level. Allow it to be set elsewhere. As noted,
    the level of the root logger only impacts ingress to the logging system.
    Do not change the root logger's level here.
    :param config_logging:
    """

    # Configure the QueueHandler first, so that messages aren't lost

    queue_handler = QueueHandler(queue)
    queue_handler.name = 'queue_handler'
    root_logger = logging.getLogger()
    root_logger.addHandler(queue_handler)

    # Remove other root handlers

    for handler in root_logger.handlers:
        if handler.name != 'queue_handler':
            root_logger.removeHandler(handler)

    set_root_logger_levels(config_logging)


def config_logger_levels(config_logging: ConfigLogging):
    set_root_logger_levels(config_logging)
    logger = pyDE1.getLogger('Logging.Config')
    for logger_name, logger_level in config_logging.LOGGERS.items():
        logger.info(f"Setting {logger_name} to {logger_level}")
        pyDE1.getLogger(logger_name).setLevel(logger_level)


def log_record_to_json(record: logging.LogRecord):
    """
    Used by the MQTT process to send an easily parsable representation
    in addition to the formatted string

    NB: message -- "The logged message, computed as msg % args.
                    This is set when Formatter.format() is invoked."
    """
    to_send = {'version': '1.0.0'}
    for attr in (
            'created',
            'levelname',
            'levelno',
            'message',
            'name',
            'process',
            'processName',
            'thread',
            'threadName'
    ):
        to_send[attr] = record.__getattribute__(attr)
    return json.dumps(to_send)


class PipeHandler (QueueHandler):
    """
    Just like a QueueHandler, except it uses a multiprocessing.Pipe's
    connection to .send() to instead of Queue.put_nowait()
    """

    def __init__(self, pipe_connection: mpc.Connection):
        logging.Handler.__init__(self)
        self.pipe_connection = pipe_connection

    def enqueue(self, record):
        self.pipe_connection.send(record)


class MemoryHandlerMulti (MemoryHandler):
    """
    Like a MemoryHandler, but uses an iterable list of targets
    """

    def flush(self):
        self.acquire()
        if self.target is None:
            return
        if isinstance(self.target, logging.Handler):
            super(MemoryHandlerMulti, self).flush()
        else:
            try:
                for this_target in self.target:
                    for record in self.buffer:
                        this_target.handle(record)
                self.buffer.clear()
            finally:
                self.release()