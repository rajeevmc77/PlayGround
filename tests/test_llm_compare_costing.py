import sys

import pytest

from llm_compare.analysis.pricing import resolve_prices
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.costing import add_usage, cost_of, split_usage
from llm_compare.domain.models import Prices, Usage


def test_tokens_split_exactly_and_cost_proportionally():
    shares = split_usage(Usage(1000, 100, 0.10), [1, 1, 2])
    assert [s.input_tokens for s in shares] == [250, 250, 500]
    assert sum(s.input_tokens for s in shares) == 1000
    assert sum(s.output_tokens for s in shares) == 100
    assert sum(s.cost for s in shares) == pytest.approx(0.10)


def test_remainders_go_to_the_largest_fractions_and_still_sum_exactly():
    shares = split_usage(Usage(10, 7, 0.0), [1, 1, 1])
    assert sum(s.input_tokens for s in shares) == 10
    assert sorted(s.input_tokens for s in shares) == [3, 3, 4]
    assert sum(s.output_tokens for s in shares) == 7


def test_zero_weights_split_equally_and_empty_weights_give_nothing():
    assert [s.input_tokens for s in split_usage(Usage(9, 0, 0.9), [0, 0, 0])] == [3, 3, 3]
    assert split_usage(Usage(9, 0, 0.9), []) == []


def test_a_single_pair_takes_the_whole_call():
    assert split_usage(Usage(123, 45, 0.5), [999]) == [Usage(123, 45, 0.5)]


def test_unknown_cost_stays_unknown():
    assert [s.cost for s in split_usage(Usage(10, 10, None), [1, 1])] == [None, None]


def test_add_usage_sums_tokens_and_cost():
    assert add_usage(Usage(1, 2, 0.5), Usage(3, 4, 0.25)) == Usage(4, 6, 0.75)
    assert add_usage(Usage(1, 2, None), Usage(3, 4, 0.25)).cost is None


def test_cost_of_uses_per_million_prices():
    assert cost_of(1_000_000, 500_000, Prices(0.30, 2.50)) == pytest.approx(0.30 + 1.25)
    assert cost_of(10, 10, None) is None


def test_config_prices_win_and_both_must_be_set():
    both = LlmCompareConfig(model="m", input_price_per_million=1.0, output_price_per_million=2.0)
    assert resolve_prices(both, lookup={}) == Prices(1.0, 2.0)
    one = LlmCompareConfig(model="m", input_price_per_million=1.0)
    assert resolve_prices(one, lookup={}) is None


def test_litellm_prices_are_used_when_the_config_has_none():
    table = {"gemini/m": {"input_cost_per_token": 3e-7, "output_cost_per_token": 2.5e-6}}
    prices = resolve_prices(LlmCompareConfig(model="m"), lookup=table)
    assert prices.input_per_million == pytest.approx(0.3)
    assert prices.output_per_million == pytest.approx(2.5)


def test_the_unprefixed_model_name_is_also_tried_and_missing_entries_give_none():
    table = {"m": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}}
    assert resolve_prices(LlmCompareConfig(model="m"), lookup=table) is not None
    assert resolve_prices(LlmCompareConfig(model="other"), lookup=table) is None
    partial = {"gemini/m": {"input_cost_per_token": 1e-6}}
    assert resolve_prices(LlmCompareConfig(model="m"), lookup=partial) is None


def test_without_litellm_installed_the_cost_is_simply_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)  # makes `import litellm` raise ImportError
    assert resolve_prices(LlmCompareConfig(model="m")) is None
