"""Runs a CPU-and-IO-heavy function over many items on a thread pool, keeping their order.

Scoring and resizing hundreds of images spends its time in Pillow, numpy and zlib, which release
the GIL, so threads scale across cores (measured: ~38 s serial -> ~5 s with 8 workers)."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(function: Callable[[T], R], items: Iterable[T], workers: int) -> list[R]:
    """`function` over `items` on up to `workers` threads; results in input order.

    One worker runs on the calling thread. A failure or Ctrl-C (any BaseException raised in
    the caller while it waits) drops the items not yet started instead of finishing them."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if workers == 1:
        return [function(item) for item in items]
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        return list(pool.map(function, items))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
