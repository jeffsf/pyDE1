"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

# TODO: When bored, camelcase() isn't quite perfect
#       <Thread(Httpserver.ServeForever_0, started 1965048928)>

# TODO: callbacks and outbound notification on fail and restart?



import asyncio
import logging
import multiprocessing
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Union, Awaitable, Callable, Optional, Mapping


def camelcase(underscored: str):
    return underscored.title().replace('_', '')


T_Work = Union[asyncio.Future, asyncio.Task, Awaitable]
#              ThreadPoolExec  create_task   generic executor


class SupervisedWork:

    def __init__(self, routine: Callable, *args, **kwargs):
        self._routine = routine
        self._args = args
        self._kwargs = kwargs
        try:
            self._name \
                = f"{routine.__self__.__class__.__name__}.{routine.__name__}"
        except AttributeError:
            self._name = routine.__name__
        self._logger = logging.getLogger(
            f"{self.__class__.__name__}.{self._name}")
        self._work = None
        self._restart_count = 0
        self._restart_count_limit = 2

    # Subclasses should self-start to be consistent with unsupervised calls
    def _start(self, task: Optional[T_Work] = None):
        if task is None:
            self._logger.info(f"Starting")
        else:
            exc = task.exception()
            if exc is None:
                self._logger.info(f"Completed without exception")
                return
            elif isinstance(exc, asyncio.CancelledError):
                self._logger.info(f"Exiting as cancelled {exc}")
                return
            else:
                self._logger.exception(f"Task failed with exception:",
                                       exc_info=exc)
                self._restart_count += 1
                if self._restart_count > self._restart_count_limit:
                    self._logger.critical("Too many restarts, abandoning")
                    return
                self._logger.info(f"Restarting")

        self._work = self._create_work()
        self._work.add_done_callback(self._start)

        return self  # Allows sw = SupervisedWork(routine, arg_list).start()

    def _create_work(self) -> T_Work:
        raise NotImplementedError

    @property
    def work(self):
        return self._work


class SupervisedTask (SupervisedWork):

    def __init__(self, routine: Callable, *args, **kwargs):
        super(SupervisedTask, self).__init__(routine, *args, **kwargs)
        self._start()

    def _create_work(self) -> T_Work:
        loop = asyncio.get_event_loop()
        work = loop.create_task(
            self._routine(*self._args, **self._kwargs),
            name=camelcase(self._name)
        )
        return work


class SupervisedExecutor (SupervisedWork):
    """
    Matches signature of loop.run_in_executor()

    NB: This assumes that the Executor returns an Awaitable
        that supports .add_done_callback()

        concurrent.futures.ThreadPoolExecutor() does
        others are not tested at this time.

    From Python BaseEventLoop:

    def set_default_executor(self, executor):
        if not isinstance(executor, concurrent.futures.ThreadPoolExecutor):
        warnings.warn(
            'Using the default executor that is not an instance of '
            'ThreadPoolExecutor is deprecated and will be prohibited '
            'in Python 3.9',
            DeprecationWarning, 2)
    """
    def __init__(self, executor: [Executor],
                 routine: Callable, *args):
        super(SupervisedExecutor, self).__init__(routine, *args)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=camelcase(self._name))
        self._executor = executor
        self._start()

    def _create_work(self) -> T_Work:
        loop = asyncio.get_event_loop()
        work = loop.run_in_executor(self._executor,
                                    self._routine, *self._args)
        return work


class SupervisedProcess:
    """
    A multiprocessing.Process that will restart itself should it terminate

    Calling SupervisedProcess.terminate() or .kill() will prevent restart
    Setting .do_not_restart will also prevent restart

    Semantics as with multiprocessing.Process()
    Needs to be explicitly started as a result

    NB: Returns a SupervisedProcess object, not a Process object

    TODO: Custom __getarg__ to delegate to Process
    """

    def __init__(self, target: Callable, name: Optional[str] = None,
                 args: Optional[tuple] = (), kwargs: Optional[Mapping] = None,
                 daemon: Optional[bool] = None,
                 do_not_restart=False):
        self._target = target
        self._name = name
        self._args = args
        self._kwargs = kwargs
        self._daemon = daemon
        self._do_not_restart = do_not_restart
        self._logger = logging.getLogger(f"SupervisedProcess.{self._name}")
        self._process: Optional[multiprocessing.Process] = None
        self._restart_count = 0
        self._restart_count_limit = 2


    def _create_process(self):
        self._process = multiprocessing.Process(
            target=self._target,
            name=self._name,
            args=self._args,
            kwargs=self._kwargs,
            daemon=self._daemon,
        )

    def start(self):

        if self._process is not None:
            if self._do_not_restart:
                self._logger.info(
                    "Not restarting as do_not_restart is set.")
                # Without dealing with the add_reader on sentinel, thrashes
                return

            if self._process.is_alive():
                self._logger.warning(
                    "Process is already running. "
                    f"Not restarting {self._process}")
                return

        # All reasons not to start eliminated

        if self._process is None:
            self._logger.info(f"Starting")
        else:
            self._restart_count += 1
            if self._restart_count > self._restart_count_limit:
                self._logger.critical("Too many restarts, abandoning")
                self.do_not_restart = True
                return
            else:
                self._logger.info(f"Restarting")

        self._create_process()
        self._process.start()
        self._logger.info(f"Started: {self._process}")

        if not self.do_not_restart:
            asyncio.get_event_loop().add_reader(self._process.sentinel,
                                                self.sentinel_cb)

    # TODO: After how many failures in how long should I give up?

    def sentinel_cb(self):
        asyncio.get_event_loop().remove_reader(self._process.sentinel)
        if self.do_not_restart:
            self._logger.info("Process exited, do-not-restart set")
        else:
            self._logger.error("Process exited")
            self.start()

    @property
    def process(self):
        return self._process

    @property
    def do_not_restart(self):
        return self._do_not_restart

    @do_not_restart.setter
    def do_not_restart(self, flag: bool):
        flag = bool(flag)
        if flag == self._do_not_restart:
            return

        if self._process is not None:
            if flag:
                asyncio.get_event_loop().remove_reader(self._process.sentinel)
            else:
                asyncio.get_event_loop().add_reader(self._process.sentinel,
                                                    self.start)
        self._do_not_restart = flag