"""load_config reads jira_config.toml text; JIRA_URL / JIRA_USERNAME /
JIRA_API_TOKEN / JIRA_PROJECT_KEY in the environment override the file."""

import pytest

from jira_backlog.config import ConfigError, load_config, load_issue_settings

FULL = """
[jira]
url = "https://example.atlassian.net/"
username = "me@example.com"
api_token = "file-token"
project_key = "AUBM"

[issues]
labels = ["aot-pulse"]
epic_name_field = "customfield_10011"
assignee_account_id = "712020:abc"

[issues.priorities]
P1 = "High"
"""


def test_load_config_reads_connection_and_issue_settings():
    config = load_config(FULL, {})

    assert config.url == "https://example.atlassian.net"
    assert (config.username, config.api_token) == ("me@example.com", "file-token")
    assert config.issues.project_key == "AUBM"
    assert config.issues.labels == ("aot-pulse",)
    assert config.issues.epic_name_field == "customfield_10011"
    assert config.issues.epic_link_field is None
    assert config.issues.priorities == {"P1": "High"}
    assert config.issues.assignee_account_id == "712020:abc"


def test_environment_overrides_the_file():
    env = {"JIRA_API_TOKEN": "env-token", "JIRA_PROJECT_KEY": "OTHER"}

    config = load_config(FULL, env)

    assert config.api_token == "env-token"
    assert config.issues.project_key == "OTHER"


def test_environment_alone_is_enough_and_defaults_apply():
    env = {"JIRA_URL": "https://x.net", "JIRA_USERNAME": "u", "JIRA_API_TOKEN": "t"}

    config = load_config(None, env)

    assert config.issues.project_key == "AUBM"
    assert (config.issues.epic_issue_type, config.issues.story_issue_type) == ("Epic", "Story")
    assert config.issues.labels == ()


def test_missing_connection_settings_are_named_in_the_error():
    with pytest.raises(ConfigError, match="username, api_token"):
        load_config('[jira]\nurl = "https://x.net"\n', {})


def test_a_blank_value_counts_as_missing():
    with pytest.raises(ConfigError, match="api_token"):
        load_config('[jira]\nurl = "u"\nusername = "n"\napi_token = "  "\n', {})


def test_invalid_toml_is_a_config_error():
    with pytest.raises(ConfigError, match="TOML"):
        load_config("[jira", {})


def test_issue_settings_load_without_any_credentials():
    settings = load_issue_settings('[issues]\nlabels = ["x"]\n', {"JIRA_PROJECT_KEY": "P"})

    assert (settings.project_key, settings.labels) == ("P", ("x",))


def test_issue_settings_of_no_file_are_the_defaults():
    assert load_issue_settings(None, {}).project_key == "AUBM"


def test_the_token_never_appears_in_the_config_repr():
    assert "file-token" not in repr(load_config(FULL, {}))
