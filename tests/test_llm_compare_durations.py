import pytest

from llm_compare.domain.durations import format_duration


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [
        (None, "n/a"),
        (0, "0 s"),
        (0.4, "0.4 s"),
        (12.4, "12.4 s"),
        (38, "38 s"),
        (38.04, "38 s"),
        (59.94, "59.9 s"),
        (59.96, "1m 00s"),
        (60, "1m 00s"),
        (252, "4m 12s"),
        (252.4, "4m 12s"),
        (3599.6, "1h 00m 00s"),
        (3785, "1h 03m 05s"),
    ],
)
def test_a_duration_is_shown_in_the_unit_that_reads_best(seconds, shown):
    assert format_duration(seconds) == shown


def test_a_negative_duration_is_shown_as_zero():
    assert format_duration(-3.0) == "0 s"
