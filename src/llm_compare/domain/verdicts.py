"""Checks that a batch response answers each numbered pair exactly once."""

from collections import Counter
from collections.abc import Sequence

from llm_compare.domain.models import PairVerdict


def validate_verdicts(
    expected_count: int, verdicts: Sequence[PairVerdict]
) -> tuple[dict[int, PairVerdict], list[int]]:
    """(usable verdicts by 1-based pair id, ids with no usable verdict). A duplicated id is
    ambiguous and so counts as missing; ids outside 1..expected_count are ignored."""
    good = _answered_once_in_batch(expected_count, verdicts)
    missing = [number for number in range(1, expected_count + 1) if number not in good]
    return good, missing


def _answered_once_in_batch(
    expected_count: int, verdicts: Sequence[PairVerdict]
) -> dict[int, PairVerdict]:
    counts = Counter(verdict.pair_id for verdict in verdicts)
    return {
        verdict.pair_id: verdict
        for verdict in verdicts
        if verdict.pair_id in range(1, expected_count + 1) and counts[verdict.pair_id] == 1
    }
