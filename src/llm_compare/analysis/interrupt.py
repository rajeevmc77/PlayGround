"""Ctrl-C for one asyncio run, made safe to press any number of times.

asyncio.run's own SIGINT handler cancels the main task on the first press but raises
KeyboardInterrupt on every later one, wherever the interpreter happens to be - including
inside asyncio's own cancellation and teardown code. Verified on Python 3.14 with real
signals: two quick presses can leave the loop waiting on tasks that were never cancelled
(a hang) or fail its teardown with "This event loop is already running", and the report is
lost. This handler never raises: every press just asks the loop to cancel the watched task.
"""

import asyncio
import signal
from collections.abc import Iterator
from contextlib import contextmanager


class CtrlC:
    def __init__(self) -> None:
        self.pressed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    def watch(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        """Called from inside the run; a press that came before it still stops the run."""
        self._loop, self._task = loop, task
        if self.pressed:
            task.cancel()

    def __call__(self, _signum, _frame) -> None:
        self.pressed = True
        if self._task is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._task.cancel)


@contextmanager
def handling_ctrl_c(handler: CtrlC) -> Iterator[None]:
    """Install `handler` for SIGINT (main thread only); asyncio.run then leaves it alone."""
    previous = signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
