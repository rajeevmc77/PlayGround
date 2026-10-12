import pytest

from llm_compare.config import ConfigError, litellm_model, load_config, parse_dotenv


def test_defaults_apply_when_nothing_is_configured():
    config = load_config("", {})
    assert config.hash_match_percent == 90.0
    assert config.max_edge == 1024
    assert config.api_key == ""
    assert config.input_price_per_million is None


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
    ],
)
def test_out_of_range_values_are_rejected(text):
    with pytest.raises(ConfigError):
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
