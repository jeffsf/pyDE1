"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""

import asyncio
import multiprocessing
import re
import time
import traceback
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Union, Awaitable, Callable, Optional, Mapping

import pyDE1
import pyDE1.shutdown_manager as sm


re_us_char = re.compile('_\w')

def upcase_us_char_match(m: re.Match):
    return m.group()[-1].upper()

def camelcase_from_underscore(underscored: str):
    all_but_first = re.sub(re_us_char, upcase_us_char_match, underscored)
    return all_but_first[0].upper() + all_but_first[1:]


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
        self._logger = pyDE1.getLogger(f"Supervised.Work.{self._name}")
        self._work = None
        self._cancelled_error: Optional[asyncio.CancelledError] = None
        self._start_time_list = []
        self._restart_count_limit = 2   # No more than 2 restarts in
        self._restart_count_window = 20 # seconds

    def _too_many_restarts(self):
        retval = False
        if len(self._start_time_list) > self._restart_count_limit:
            n_ago = self._start_time_list[-(self._restart_count_limit + 1)]
            dt = time.time() - n_ago
            retval = dt < self._restart_count_window
        return retval

    def _record_start(self):
        # For now, just use a simple append
        self._start_time_list.append(time.time())
        # but check if it gets crazy long
        if len(self._start_time_list) > 2 * self._restart_count_limit:
            self._logger.warning(
                f"Start-time list seems long: {len(self._start_time_list)}")

    # Subclasses should self-start to be consistent with unsupervised calls
    def _start(self, task: Optional[T_Work] = None):
        if task is None:
            self._logger.info(f"Starting")
        else:
            exc = task.exception()
            if exc is None \
                    and not task.cancelled() \
                    and not self._cancelled_error:
                self._logger.info(
                    f"Exiting as completed without exception")
                return
            # asyncio.CancelledError == asyncio.exceptions.CancelledError
            # True
            elif self._cancelled_error:
                self._logger.info(
                    f"Exiting as cancelled with '{self._cancelled_error}'")
                return
            elif task.cancelled():
                self._logger.info(
                    f"Exiting as task.cancelled()")
                return
            else:
                self._logger.exception(
                    f"Task failed with exception:", exc_info=exc)
                if self._too_many_restarts():
                    self._logger.critical("Too many restarts, abandoning")
                    self._logger.critical("Calling shutdown")
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(sm.shutdown(None, loop))
                    else:
                        loop.run_until_complete(sm.shutdown(None, loop))
                    return
                self._logger.info(f"Restarting")

        self._work = self._create_work()
        self._record_start()
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
        self._logger = pyDE1.getLogger(f"Supervised.Task.{self._name}")
        self._start()

    def _create_work(self) -> T_Work:
        loop = asyncio.get_event_loop()
        async def wrapped(st: SupervisedTask):
            inner_task = st._routine(*st._args, **st._kwargs)
            try:
                await inner_task
            except asyncio.CancelledError as e:
                st._logger.debug(
                    f"{e}: {inner_task}")
                st._cancelled_error = e

        work = loop.create_task(
            wrapped(self),
            name=camelcase_from_underscore(self._name)
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
        self._logger = pyDE1.getLogger(f"Supervised.Executor.{self._name}")
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=camelcase_from_underscore(self._name))
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
        self._logger = pyDE1.getLogger(f"Supervised.Process.{self._name}")
        self._process: Optional[multiprocessing.Process] = None
        self._start_time_list = []
        self._restart_count_limit = 2  # No more than 2 restarts in
        self._restart_count_window = 20  # seconds

    def _too_many_restarts(self):
        retval = False
        if len(self._start_time_list) > self._restart_count_limit:
            n_ago = self._start_time_list[-(self._restart_count_limit + 1)]
            dt = time.time() - n_ago
            retval = dt < self._restart_count_window
        return retval

    def _record_start(self):
        # For now, just use a simple append
        self._start_time_list.append(time.time())
        # but check if it gets crazy long
        if len(self._start_time_list) > 2 * self._restart_count_limit:
            self._logger.warning(
                f"Start-time list seems long: {len(self._start_time_list)}")

    def _wrap_target(self, *args, **kwargs):
        try:
            self._target(*args, **kwargs)
        except Exception as exc:
            tbe = traceback.TracebackException.from_exception(exc)
            self._logger.error(
                f"Shutting down on exception: {''.join(tbe.format())}")
            if (loop := asyncio.get_event_loop()).is_running():
                self._logger.debug(f"Have running loop: {loop}")
                loop.create_task(sm.shutdown(None, loop))
            else:
                self._logger.debug("No running loop")
                loop.run_until_complete(sm.shutdown(None, loop))

    def _create_process(self):
        self._process = multiprocessing.Process(
            target=self._wrap_target,
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
            if self._too_many_restarts():
                self._logger.critical("Too many restarts, abandoning")
                self.do_not_restart = True
                self._logger.critical("Calling shutdown")
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(sm.shutdown(None, loop))
                else:
                    loop.run_until_complete(sm.shutdown(None, loop))
                return
            else:
                self._logger.info(f"Restarting")

        self._create_process()
        self._process.start()
        self._record_start()
        self._logger.info(f"Started: {self._process}")

        if not self.do_not_restart:
            asyncio.get_event_loop().add_reader(self._process.sentinel,
                                                self.sentinel_cb)

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