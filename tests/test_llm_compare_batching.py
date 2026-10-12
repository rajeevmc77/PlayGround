import pytest

from llm_compare.domain.batching import estimate_call_tokens, estimate_image_tokens, pack
from tests.llm_compare_support import prepared_pair


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(300, 200, 258), (384, 384, 258), (1000, 1000, 1032), (1024, 300, 2064), (385, 10, 516)],
)
def test_image_tokens_follow_the_gemini_tiling_rule(width, height, expected):
    assert estimate_image_tokens(width, height) == expected


def test_the_calibration_scale_adjusts_the_estimate():
    assert estimate_image_tokens(1000, 1000, scale=0.5) == 516
    assert estimate_image_tokens(300, 200, scale=1.5) == 387


def _pairs(count, tokens=1000):
    return [prepared_pair(f"K{n}", tokens=tokens) for n in range(count)]


def test_pack_respects_the_pair_limit_and_keeps_order():
    batches = pack(_pairs(7), max_pairs=3, max_input_tokens=10**9)
    assert [[p.key for p in b] for b in batches] == [["K0", "K1", "K2"], ["K3", "K4", "K5"], ["K6"]]


def test_pack_respects_the_token_budget_including_overhead():
    batches = pack(_pairs(5), max_pairs=10, max_input_tokens=2500, overhead=600)
    assert [len(b) for b in batches] == [1, 1, 1, 1, 1]
    batches = pack(_pairs(5), max_pairs=10, max_input_tokens=3000, overhead=600)
    assert [len(b) for b in batches] == [2, 2, 1]


def test_one_oversize_pair_still_gets_its_own_call():
    batches = pack([prepared_pair("big", tokens=10**6), *_pairs(2)], 5, max_input_tokens=5000)
    assert [[p.key for p in b] for b in batches] == [["big"], ["K0", "K1"]]


def test_no_pairs_means_no_batches():
    assert pack([], max_pairs=3, max_input_tokens=1000) == []


def test_call_estimate_adds_overhead_and_output_allowance():
    batch = _pairs(3, tokens=1000)
    assert estimate_call_tokens(batch, overhead=700, output_per_pair=150) == 3000 + 700 + 450
