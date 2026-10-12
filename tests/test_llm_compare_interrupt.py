import asyncio
import signal

import pytest

from llm_compare.analysis.interrupt import CtrlC, handling_ctrl_c


def test_a_press_before_the_run_is_watched_still_cancels_it():
    ctrl_c = CtrlC()
    ctrl_c(signal.SIGINT, None)

    async def run():
        ctrl_c.watch(asyncio.get_running_loop(), asyncio.current_task())
        await asyncio.sleep(2)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())


def test_presses_cancel_the_watched_task_from_inside_the_loop_and_never_raise():
    ctrl_c = CtrlC()

    async def run():
        ctrl_c.watch(asyncio.get_running_loop(), asyncio.current_task())
        for _ in range(3):
            ctrl_c(signal.SIGINT, None)
        await asyncio.sleep(2)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert ctrl_c.pressed


def test_a_press_after_the_loop_has_closed_is_harmless():
    ctrl_c = CtrlC()

    async def run():
        ctrl_c.watch(asyncio.get_running_loop(), asyncio.current_task())

    asyncio.run(run())
    ctrl_c(signal.SIGINT, None)
    assert ctrl_c.pressed


def test_the_handler_is_installed_only_for_the_block():
    ctrl_c = CtrlC()
    before = signal.getsignal(signal.SIGINT)
    with handling_ctrl_c(ctrl_c):
        assert signal.getsignal(signal.SIGINT) is ctrl_c
    assert signal.getsignal(signal.SIGINT) is before
