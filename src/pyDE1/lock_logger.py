"""
Copyright © 2021-2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Class to provide logging of waiting for locks

Typical usage:

        ll = LockLogger(some_lock, 'Name of lock').check()
        async with some_lock:
            ll.acquired()
            await something_under_some_lock()
        ll.released()
"""

import asyncio
import inspect
import time

import pyDE1


class LockLogger:

    def __init__(self, lock: asyncio.Lock, name: str):
        self._lock = lock
        self._name = name
        self._logger = pyDE1.getLogger(f'Lock.{self._name}')
        self._checked = None
        self._acquired = None

    def check(self) -> 'LockLogger':
        if self._lock.locked():
            self._checked = time.time()
            self._logger.warning(
                f"Waiting for lock {repr(self._lock)} {self.call_str()}")
        else:
            self._checked = None
        return self  # Allows lock_logger = LockLogger(...).check()

    def acquired(self, full_trace=False):
        self._acquired = time.time()
        if self._checked:
            dt = (self._acquired - self._checked) * 1000
            # Warning here allows setting log level to warning
            # and still seeing how long the waits were
            self._logger.warning(
                f"Acquired lock after {dt:.0f} ms {self.call_str(full_trace)}")
        else:
            self._logger.info(
                f"Acquired lock {self.call_str()}")

    def released(self, full_trace=False):
        dt = (time.time() - self._acquired) * 1000
        if self._lock.locked():
            self._logger.error(
                f"NOT RELEASED after {dt:.0f} ms {self.call_str()}")
        else:
            self._logger.info(
                f"Released lock after {dt:.0f} ms {self.call_str(full_trace)}")

    @staticmethod
    def call_str(full_trace=True):
        stack = inspect.stack()[2]
        retval = f"at {stack.function}:{stack.lineno}"
        if full_trace:
            idx = 3
            while True:
                try:
                    stack = inspect.stack()[idx]
                    next_caller = f"{stack.function}:{stack.lineno}"
                    if stack.function.startswith('_run'):
                        break
                    retval = f"{retval} < {next_caller}"
                except IndexError:
                    break
                idx += 1
        return retval

