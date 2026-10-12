import pytest

from llm_compare.domain.errors import JudgeError, Permanent, RateLimited, Transient
from llm_compare.domain.models import PairVerdict, Route, Verdict
from llm_compare.domain.selection import route_for
from llm_compare.domain.verdicts import validate_verdicts
from tests.llm_compare_support import image_pair, prepared_pair


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (89.9, Route.TO_LLM),
        (90.0, Route.MATCH_PHASH),
        (100.0, Route.MATCH_PHASH),
        (0.0, Route.TO_LLM),
    ],
)
def test_route_for_is_inclusive_at_the_threshold(score, expected):
    assert route_for(score, 90.0) is expected


def test_route_for_uses_the_given_threshold():
    assert route_for(85.0, 80.0) is Route.MATCH_PHASH


def _verdict(number, verdict=Verdict.IDENTICAL):
    return PairVerdict(number, verdict, ())


def test_every_expected_id_answered_once_is_good():
    good, missing = validate_verdicts(2, [_verdict(2), _verdict(1)])
    assert sorted(good) == [1, 2] and missing == []


def test_a_missing_id_is_reported():
    good, missing = validate_verdicts(3, [_verdict(1), _verdict(3)])
    assert sorted(good) == [1, 3] and missing == [2]


def test_a_duplicated_id_is_treated_as_missing():
    good, missing = validate_verdicts(2, [_verdict(1), _verdict(1, Verdict.DIFFERENT), _verdict(2)])
    assert sorted(good) == [2] and missing == [1]


def test_ids_outside_the_batch_are_ignored():
    good, missing = validate_verdicts(2, [_verdict(0), _verdict(1), _verdict(9)])
    assert sorted(good) == [1] and missing == [2]


def test_no_verdicts_means_everything_is_missing():
    assert validate_verdicts(2, []) == ({}, [1, 2])
    assert validate_verdicts(0, []) == ({}, [])


def test_judge_errors_share_a_base_and_rate_limits_carry_retry_after():
    assert issubclass(RateLimited, JudgeError)
    assert issubclass(Transient, JudgeError) and issubclass(Permanent, JudgeError)
    assert RateLimited("slow down", retry_after=7.0).retry_after == 7.0
    assert RateLimited("slow down").retry_after is None


def test_support_builders_make_consistent_objects():
    pair = prepared_pair("B.Eq1", tokens=250)
    assert (pair.key, pair.row_id, pair.tokens) == ("B.Eq1", "pdf:images/a.png", 250)
    assert image_pair("X").web_path == "web_images/a.png"
