"""
Utility to catch and log task exceptions

Source: https://quantlane.com/blog/ensure-asyncio-task-exceptions-get-logged/

    HOW WE MADE THIS ERROR HANDLING REUSABLE

    Since long-running tasks are a common pattern in our code we created
    a utility function to set up all these error handlers for us.
    This is our task_logger.py module.
    It is MIT-licenced, so feel free to use and modify for your own needs:

    The full example code taking advantage of this follows.
    We simply use task_logger.create_task on line 22
    and provide a bit of context to it.

 1 import asyncio
 2 import logging
 3
 4 import task_logger
 5
 6
 7 async def problem() -> None:
 8     await asyncio.sleep(1)
 9     logging.warning('Going to raise an exception now!')
10     raise RuntimeError('Something went wrong')
11
12
13 if __name__ == '__main__':
14     logging.basicConfig(
15         format = '▸ %(asctime)s.%(msecs)03d %(filename)s:%(lineno)d %(levelname)s %(message)s',
16         level = logging.INFO,
17         datefmt = '%H:%M:%S',
18     )
19     loop = asyncio.get_event_loop()
20     logging.info('Creating the problem task')
21     logger = logging.getLogger('task_logger')
22     task = task_logger.create_task(problem(), logger = logger, message = 'Task raised an exception', loop = loop)
23     logging.info('Created task = %r', task)
24     logging.info('Running the loop')
25     try:
26         loop.run_forever()
27     except KeyboardInterrupt:
28         logging.info('Closing the loop')
29         loop.close()
30     logging.info('Shutting down')

        Written by Vita Smid on June 26, 2020.
"""
from typing import Any, Awaitable, Optional, TypeVar, Tuple

import asyncio
import functools
import logging


T = TypeVar('T')


def create_task(
    coroutine: Awaitable[T],
    *,
    logger: logging.Logger,
    message: str,
    message_args: Tuple[Any, ...] = (),
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> 'asyncio.Task[T]':  # This type annotation has to be quoted for Python < 3.9, see https://www.python.org/dev/peps/pep-0585/
    '''
    This helper function wraps a ``loop.create_task(coroutine())`` call and ensures there is
    an exception handler added to the resulting task. If the task raises an exception it is logged
    using the provided ``logger``, with additional context provided by ``message`` and optionally
    ``message_args``.
    '''
    if loop is None:
        loop = asyncio.get_running_loop()
    task = loop.create_task(coroutine)
    task.add_done_callback(
        functools.partial(_handle_task_result, logger = logger, message = message, message_args = message_args)
    )
    return task


def _handle_task_result(
    task: asyncio.Task,
    *,
    logger: logging.Logger,
    message: str,
    message_args: Tuple[Any, ...] = (),
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass  # Task cancellation should not be logged as an error.
    # Ad the pylint ignore: we want to handle all exceptions here so that the result of the task
    # is properly logged. There is no point re-raising the exception in this callback.
    except Exception:  # pylint: disable=broad-except
        logger.exception(message, *message_args)

