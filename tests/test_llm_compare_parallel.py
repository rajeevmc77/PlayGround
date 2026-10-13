import threading
import time

import pytest

from llm_compare.analysis.parallel import parallel_map


def test_results_keep_the_input_order_though_items_finish_out_of_order():
    def slow_first(number):
        time.sleep(0.05 if number == 0 else 0)
        return number * 10

    assert parallel_map(slow_first, range(6), workers=4) == [0, 10, 20, 30, 40, 50]


def test_items_really_run_at_the_same_time():
    barrier = threading.Barrier(3, timeout=5)

    def meet(number):
        barrier.wait()  # every worker waits here: sequential execution would break the barrier
        return number

    assert parallel_map(meet, [1, 2, 3], workers=3) == [1, 2, 3]


def test_one_worker_stays_on_the_calling_thread_in_order():
    seen = []

    def note(number):
        seen.append((number, threading.current_thread()))
        return number

    assert parallel_map(note, [1, 2, 3], workers=1) == [1, 2, 3]
    assert [thread for _, thread in seen] == [threading.current_thread()] * 3


def test_no_items_gives_no_results():
    assert parallel_map(lambda number: number, [], workers=4) == []


def test_a_failure_propagates_and_items_not_yet_started_never_run():
    started = []

    def fail_first(number):
        started.append(number)
        if number == 0:
            raise RuntimeError("boom")
        time.sleep(0.05)

    with pytest.raises(RuntimeError, match="boom"):
        parallel_map(fail_first, range(50), workers=2)
    assert len(started) < 10


def test_workers_below_one_is_rejected():
    with pytest.raises(ValueError, match="workers"):
        parallel_map(lambda number: number, [1], workers=0)
