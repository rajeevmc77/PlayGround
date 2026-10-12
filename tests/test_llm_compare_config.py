from pathlib import Path

import pytest

from llm_compare.config import ConfigError, litellm_model, load_config, parse_dotenv


def test_defaults_apply_when_nothing_is_configured():
    config = load_config("", {})
    assert config.hash_match_percent == 90.0
    assert config.max_edge == 1024
    assert config.api_key == ""
    assert config.input_price_per_million is None
    assert config.max_output_tokens == 8192


def test_the_output_estimate_defaults_to_what_low_reasoning_answers_measured_at():
    config = load_config("", {})
    assert config.output_tokens_per_pair == 300
    # a 6-pair call's estimate must fit the output cap, thinking headroom included
    assert config.output_tokens_per_pair * config.max_pairs_per_call < config.max_output_tokens


def test_the_example_config_file_loads_and_documents_the_output_cap():
    example = Path(__file__).resolve().parent.parent / "llm_compare_config.example.toml"
    assert load_config(example.read_text(), {}).max_output_tokens == 8192


def test_the_example_config_documents_reasoning_effort_and_still_loads_with_it_enabled():
    example = Path(__file__).resolve().parent.parent / "llm_compare_config.example.toml"
    text = example.read_text()
    assert '# reasoning_effort = "low"' in text
    enabled = text.replace('# reasoning_effort = "low"', 'reasoning_effort = "low"')
    assert load_config(enabled, {}).reasoning_effort == "low"


def test_max_output_tokens_is_a_whole_number_of_at_least_one():
    assert load_config("max_output_tokens = 2048", {}).max_output_tokens == 2048
    with pytest.raises(ConfigError, match="max_output_tokens must be at least 1"):
        load_config("max_output_tokens = 0", {})
    with pytest.raises(ConfigError, match="max_output_tokens must be a whole number"):
        load_config("max_output_tokens = 1.5", {})


def test_toml_values_override_defaults():
    config = load_config("rpm = 12\nhash_match_percent = 85\n", {})
    assert (config.rpm, config.hash_match_percent) == (12, 85.0)


def test_environment_beats_dotenv_beats_toml_for_the_model():
    toml = 'model = "from-toml"\n'
    assert load_config(toml, {"GEMINI_MODEL": "env"}, {"GEMINI_MODEL": "dot"}).model == "env"
    assert load_config(toml, {}, {"GEMINI_MODEL": "dot"}).model == "dot"
    assert load_config(toml, {}, {}).model == "from-toml"


def test_api_key_comes_from_environment_or_dotenv_only():
    assert load_config("", {}, {"GEMINI_API_KEY": "k"}).api_key == "k"
    assert load_config("", {"GEMINI_API_KEY": "e"}, {"GEMINI_API_KEY": "k"}).api_key == "e"
    with pytest.raises(ConfigError, match="api_key"):
        load_config('api_key = "secret"', {})


@pytest.mark.parametrize(
    "text",
    [
        "rpm = 0",
        "hash_match_percent = 0",
        "hash_match_percent = 101",
        "max_pairs_per_call = 0",
        "tpm = -5",
        "single_retries = -1",
        "input_price_per_million = -1",
        "token_scale = 0",
        "request_timeout_seconds = 0",
        "request_timeout_seconds = -1",
        "request_timeout_seconds = inf",
        "request_timeout_seconds = nan",
    ],
)
def test_out_of_range_values_are_rejected(text):
    with pytest.raises(ConfigError):
        load_config(text, {})


@pytest.mark.parametrize(
    "text, message",
    [
        ("model = 5", "model must be text"),
        ('retry_base_delay = "x"', "retry_base_delay must be a number"),
        ("token_scale = true", "token_scale must be a number"),
        ("rpm = 1.5", "rpm must be a whole number"),
    ],
)
def test_wrong_value_types_name_the_setting(text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(text, {})


@pytest.mark.parametrize("text", ["nonsense = 1", 'rpm = "ten"', "rpm = true", "= broken"])
def test_unknown_keys_wrong_types_and_bad_toml_are_rejected(text):
    with pytest.raises(ConfigError):
        load_config(text, {})


def test_prices_are_optional_and_accept_integers():
    config = load_config("input_price_per_million = 1\noutput_price_per_million = 2.5", {})
    assert (config.input_price_per_million, config.output_price_per_million) == (1.0, 2.5)


def test_parse_dotenv_reads_plain_quoted_and_exported_lines():
    text = "# comment\n\nGEMINI_API_KEY=\"abc\"\nexport X=1\nBAD LINE\nQ='v'\nEMPTY=\n"
    assert parse_dotenv(text) == {"GEMINI_API_KEY": "abc", "X": "1", "Q": "v", "EMPTY": ""}


def test_litellm_model_adds_the_gemini_prefix_once():
    assert litellm_model("gemini-3.8-flash") == "gemini/gemini-3.8-flash"
    assert litellm_model("gemini/gemini-3.8-flash") == "gemini/gemini-3.8-flash"
    assert litellm_model("") == ""


def test_request_timeout_defaults_to_two_minutes_and_can_be_overridden():
    assert load_config("", {}).request_timeout_seconds == 120.0
    assert load_config("request_timeout_seconds = 45", {}).request_timeout_seconds == 45.0
    assert load_config("request_timeout_seconds = 0.5", {}).request_timeout_seconds == 0.5


def test_request_timeout_must_be_a_number():
    with pytest.raises(ConfigError, match="request_timeout_seconds must be a number"):
        load_config('request_timeout_seconds = "soon"', {})
    with pytest.raises(ConfigError, match="request_timeout_seconds must be above 0"):
        load_config("request_timeout_seconds = 0", {})


ALLOWED_EFFORTS = ["", "minimal", "low", "medium", "high", "off"]


def test_reasoning_effort_defaults_to_low():
    assert load_config("", {}).reasoning_effort == "low"


@pytest.mark.parametrize("effort", ALLOWED_EFFORTS)
def test_reasoning_effort_accepts_each_allowed_value_from_the_file(effort):
    assert load_config(f'reasoning_effort = "{effort}"', {}).reasoning_effort == effort


@pytest.mark.parametrize("effort", ["max", "LOW", "Low", " low", "none"])
def test_an_unknown_or_differently_cased_reasoning_effort_names_the_allowed_values(effort):
    with pytest.raises(ConfigError, match="reasoning_effort must be one of") as raised:
        load_config(f'reasoning_effort = "{effort}"', {})
    assert all(f'"{allowed}"' in str(raised.value) for allowed in ALLOWED_EFFORTS)


@pytest.mark.parametrize("value", ["5", "true", "['low']"])
def test_a_non_text_reasoning_effort_is_rejected(value):
    with pytest.raises(ConfigError, match="reasoning_effort must be text"):
        load_config(f"reasoning_effort = {value}", {})


def test_reasoning_effort_is_not_read_from_the_environment():
    env = {"REASONING_EFFORT": "high", "GEMINI_REASONING_EFFORT": "high"}
    assert load_config("", env, env).reasoning_effort == "low"
