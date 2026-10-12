import asyncio

import pytest

from llm_compare.analysis.limiter import RateLimiter, call_with_retries
from llm_compare.domain.errors import Permanent, RateLimited, Transient


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _limiter(fake, rpm=100, tpm=10_000):
    return RateLimiter(rpm, tpm, clock=fake.clock, sleep=fake.sleep)


def test_requests_over_the_per_minute_budget_wait_for_the_window():
    fake = FakeTime()
    limiter = _limiter(fake, rpm=2)

    async def go():
        for _ in range(3):
            await limiter.acquire(1)

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def test_tokens_over_the_per_minute_budget_wait_too():
    fake = FakeTime()
    limiter = _limiter(fake, tpm=100)

    async def go():
        await limiter.acquire(60)
        await limiter.acquire(60)

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def test_the_window_slides_so_only_the_remaining_time_is_waited():
    fake = FakeTime()
    limiter = _limiter(fake, rpm=2)

    async def go():
        await limiter.acquire(1)
        fake.now = 30.0
        await limiter.acquire(1)
        await limiter.acquire(1)

    asyncio.run(go())
    assert fake.sleeps == [30.0]


def test_one_call_bigger_than_the_whole_token_budget_does_not_deadlock():
    fake = FakeTime()
    limiter = _limiter(fake, tpm=100)

    async def go():
        await limiter.acquire(500)
        await limiter.acquire(1)

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def test_releasing_with_actual_usage_frees_unused_budget():
    fake = FakeTime()
    limiter = _limiter(fake, tpm=100)

    async def go():
        reservation = await limiter.acquire(90)
        limiter.release(reservation, 10)
        await limiter.acquire(80)

    asyncio.run(go())
    assert fake.sleeps == []


def test_concurrent_acquirers_share_the_budget():
    fake = FakeTime()
    limiter = _limiter(fake, rpm=1)

    async def go():
        await asyncio.gather(limiter.acquire(1), limiter.acquire(1))

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def _flaky(errors, result="ok"):
    pending = list(errors)

    async def call():
        if pending:
            raise pending.pop(0)
        return result

    return call


def _retry(call, fake=None, attempts=5, jitter=lambda: 1.0):
    fake = fake or FakeTime()
    outcome = asyncio.run(
        call_with_retries(
            call, attempts=attempts, base_delay=1.0, max_delay=3.0, sleep=fake.sleep, jitter=jitter
        )
    )
    return outcome, fake


def test_transient_errors_back_off_exponentially_up_to_the_cap():
    outcome, fake = _retry(_flaky([Transient("503")] * 3))
    assert outcome == "ok" and fake.sleeps == [1.0, 2.0, 3.0]


def test_jitter_scales_the_delay_between_half_and_full():
    _, fake = _retry(_flaky([Transient("503")]), jitter=lambda: 0.0)
    assert fake.sleeps == [0.5]


def test_retry_after_is_honoured_over_the_backoff():
    _, fake = _retry(_flaky([RateLimited("429", retry_after=7.0)]))
    assert fake.sleeps == [7.0]


def test_permanent_errors_are_not_retried():
    fake = FakeTime()
    with pytest.raises(Permanent):
        _retry(_flaky([Permanent("400")]), fake)
    assert fake.sleeps == []


def test_the_last_error_surfaces_when_attempts_run_out():
    fake = FakeTime()
    with pytest.raises(Transient):
        _retry(_flaky([Transient("503")] * 5), fake, attempts=3)
    assert len(fake.sleeps) == 2
