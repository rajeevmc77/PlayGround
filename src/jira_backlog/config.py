"""JIRA connection and issue settings, read from jira_config.toml text with
the JIRA_URL / JIRA_USERNAME / JIRA_API_TOKEN / JIRA_PROJECT_KEY environment
variables taking precedence (so the token can stay out of the file)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field

from jira_backlog.jira.fields import IssueSettings

DEFAULT_PROJECT_KEY = "AUBM"
_ENV = {"url": "JIRA_URL", "username": "JIRA_USERNAME", "api_token": "JIRA_API_TOKEN"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class JiraConfig:
    url: str
    username: str
    api_token: str = field(repr=False)
    issues: IssueSettings


def load_config(text: str | None, env: Mapping[str, str]) -> JiraConfig:
    data = _parse(text or "")
    connection = _connection(data.get("jira", {}), env)
    return JiraConfig(
        url=connection["url"].rstrip("/"),
        username=connection["username"],
        api_token=connection["api_token"],
        issues=_issue_settings(data, env),
    )


def _connection(jira: dict, env: Mapping[str, str]) -> dict[str, str]:
    connection = {name: env.get(var) or jira.get(name, "") for name, var in _ENV.items()}
    missing = [name for name, value in connection.items() if not str(value).strip()]
    if missing:
        raise ConfigError(f"missing JIRA settings: {', '.join(missing)}")
    return connection


def load_issue_settings(text: str | None, env: Mapping[str, str]) -> IssueSettings:
    """Just the issue settings - enough for a dry run, which needs no credentials."""
    return _issue_settings(_parse(text or ""), env)


def _parse(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"jira config is not valid TOML: {error}") from error


def _issue_settings(data: dict, env: Mapping[str, str]) -> IssueSettings:
    jira, issues = data.get("jira", {}), data.get("issues", {})
    return IssueSettings(
        project_key=env.get("JIRA_PROJECT_KEY") or jira.get("project_key", DEFAULT_PROJECT_KEY),
        epic_issue_type=issues.get("epic_issue_type", "Epic"),
        story_issue_type=issues.get("story_issue_type", "Story"),
        labels=tuple(issues.get("labels", ())),
        epic_name_field=issues.get("epic_name_field") or None,
        epic_link_field=issues.get("epic_link_field") or None,
        assignee_account_id=issues.get("assignee_account_id") or None,
        priorities=dict(issues.get("priorities", {})),
    )
