import pytest

from mo_toc.parsing.marker_rules import RE_MARKER, classify_marker


@pytest.mark.parametrize(
    "token,expected",
    [
        ("1", "sentence"),
        ("23", "sentence"),
        ("a", "clause"),
        ("b", "clause"),
        ("z", "clause"),
        ("i", "ambiguous"),
        ("v", "ambiguous"),
        ("x", "ambiguous"),
        ("ii", "subclause"),
        ("iv", "subclause"),
        ("xii", "subclause"),
        ("iz", "noise"),
        ("q1", "noise"),
    ],
)
def test_classify_marker(token, expected):
    assert classify_marker(token) == expected


def test_re_marker_matches_sentence_line():
    m = RE_MARKER.match("1) Fire protection shall conform to...")
    assert m is not None
    assert m.group(1) == "1"
    assert m.group(2) == "Fire protection shall conform to..."


def test_re_marker_matches_clause_line():
    m = RE_MARKER.match("a) the design must account for...")
    assert m.group(1) == "a"


def test_re_marker_rejects_non_marker_line():
    assert RE_MARKER.match("This is ordinary body text.") is None


def test_re_marker_rejects_overlong_token():
    assert RE_MARKER.match("abcde) too long") is None
