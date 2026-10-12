"""Settings for the LLM image comparison, read from llm_compare_config.toml text plus
GEMINI_API_KEY / GEMINI_MODEL (environment first, then .env, then the file for the model)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields


class ConfigError(ValueError):
    """The settings are unusable; the message says which one and why."""


@dataclass(frozen=True)
class LlmCompareConfig:
    api_key: str = ""
    model: str = ""
    hash_match_percent: float = 90.0
    max_edge: int = 1024
    max_pairs_per_call: int = 6
    max_input_tokens: int = 60_000
    call_overhead_tokens: int = 700
    output_tokens_per_pair: int = 150
    token_scale: float = 1.0
    rpm: int = 30
    tpm: int = 250_000
    workers: int = 4
    single_retries: int = 2
    retry_attempts: int = 5
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None


_INT_KEYS = (
    "max_edge",
    "max_pairs_per_call",
    "max_input_tokens",
    "call_overhead_tokens",
    "output_tokens_per_pair",
    "rpm",
    "tpm",
    "workers",
    "single_retries",
    "retry_attempts",
)
_FLOAT_KEYS = (
    "hash_match_percent",
    "token_scale",
    "retry_base_delay",
    "retry_max_delay",
    "input_price_per_million",
    "output_price_per_million",
)
_FILE_KEYS = {f.name for f in fields(LlmCompareConfig)} - {"api_key"}


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        values[name.strip()] = raw.strip().strip("\"'")
    return values


def litellm_model(model: str) -> str:
    return model if not model or "/" in model else f"gemini/{model}"


def _require_int(name: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be a whole number")
    return value


def _require_number(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{name} must be a number")
    return float(value)


def _require_text(name: str, value) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be text")
    return value


def _coerce(name: str, value):
    if name in _INT_KEYS:
        return _require_int(name, value)
    if name in _FLOAT_KEYS:
        return _require_number(name, value)
    return _require_text(name, value)


def _read_values(toml_text: str) -> dict:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"llm_compare_config.toml is not valid TOML: {error}") from error
    unknown = sorted(set(data) - _FILE_KEYS)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(unknown)}")
    return {name: _coerce(name, value) for name, value in data.items()}


def _check_ints(config: LlmCompareConfig) -> None:
    for name in _INT_KEYS:
        minimum = 0 if name == "single_retries" else 1
        if getattr(config, name) < minimum:
            raise ConfigError(f"{name} must be at least {minimum}")


def _check_floats(config: LlmCompareConfig) -> None:
    if not 0 < config.hash_match_percent <= 100:
        raise ConfigError("hash_match_percent must be above 0 and at most 100")
    if config.token_scale <= 0:
        raise ConfigError("token_scale must be above 0")
    for name in _FLOAT_KEYS:
        value = getattr(config, name)
        if value is not None and value < 0:
            raise ConfigError(f"{name} must not be negative")


def load_config(
    toml_text: str, env: Mapping[str, str], dotenv: Mapping[str, str] | None = None
) -> LlmCompareConfig:
    dotenv = dotenv or {}
    values = _read_values(toml_text)
    file_model = values.pop("model", "")
    model = env.get("GEMINI_MODEL") or dotenv.get("GEMINI_MODEL") or file_model
    api_key = env.get("GEMINI_API_KEY") or dotenv.get("GEMINI_API_KEY") or ""
    config = LlmCompareConfig(api_key=api_key, model=model, **values)
    _check_ints(config)
    _check_floats(config)
    return config
