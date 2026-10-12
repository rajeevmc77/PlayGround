"""Per-million-token prices: the config's when both are set, else LiteLLM's table."""

from collections.abc import Mapping

from llm_compare.config import LlmCompareConfig, litellm_model
from llm_compare.domain.models import Prices


def _litellm_table() -> Mapping:
    try:
        import litellm
    except ImportError:
        return {}
    return litellm.model_cost


def _from_table(model: str, table: Mapping) -> Prices | None:
    entry = table.get(model) or table.get(model.split("/", 1)[-1])
    if not entry:
        return None
    per_input, per_output = entry.get("input_cost_per_token"), entry.get("output_cost_per_token")
    if per_input is None or per_output is None:
        return None
    return Prices(per_input * 1_000_000, per_output * 1_000_000)


def resolve_prices(config: LlmCompareConfig, lookup: Mapping | None = None) -> Prices | None:
    if config.input_price_per_million is not None and config.output_price_per_million is not None:
        return Prices(config.input_price_per_million, config.output_price_per_million)
    table = lookup if lookup is not None else _litellm_table()
    return _from_table(litellm_model(config.model), table)
