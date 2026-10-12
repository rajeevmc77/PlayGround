"""Keeps async calls inside the provider's requests- and tokens-per-minute limits, and
retries the failures that retrying can cure."""

import asyncio
import random
import time
from collections import deque

from llm_compare.domain.errors import RateLimited, Transient


class RateLimiter:
    """Sliding-window limiter. `acquire` reserves an estimate and waits if either budget
    would be exceeded; `release` corrects the reservation with the real usage. One request
    larger than the whole token budget is let through when nothing else is in the window."""

    def __init__(self, rpm, tpm, clock=time.monotonic, sleep=asyncio.sleep, window=60.0):
        self._rpm, self._tpm, self._window = rpm, tpm, window
        self._clock, self._sleep = clock, sleep
        self._entries: deque[list] = deque()
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= self._window:
            self._entries.popleft()

    def _wait_needed(self, now: float, tokens: int) -> float:
        if not self._entries:
            return 0.0
        over_requests = len(self._entries) >= self._rpm
        over_tokens = sum(entry[1] for entry in self._entries) + tokens > self._tpm
        if not (over_requests or over_tokens):
            return 0.0
        return self._entries[0][0] + self._window - now

    async def acquire(self, tokens: int) -> list:
        async with self._lock:
            while True:
                now = self._clock()
                self._prune(now)
                wait = self._wait_needed(now, tokens)
                if wait <= 0:
                    entry = [now, tokens]
                    self._entries.append(entry)
                    return entry
                await self._sleep(wait)

    def release(self, reservation: list, actual_tokens: int) -> None:
        reservation[1] = actual_tokens


def _delay(error, attempt, base_delay, max_delay, jitter) -> float:
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None:
        return retry_after
    return min(max_delay, base_delay * 2**attempt) * (0.5 + 0.5 * jitter())


async def call_with_retries(
    call, *, attempts, base_delay, max_delay, sleep=asyncio.sleep, jitter=random.random
):
    for attempt in range(attempts):
        try:
            return await call()
        except (RateLimited, Transient) as error:
            if attempt == attempts - 1:
                raise
            await sleep(_delay(error, attempt, base_delay, max_delay, jitter))
