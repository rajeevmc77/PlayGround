"""Publishes a backlog: each epic, then its stories under it. Every created
key goes into the state right away, so a run that fails part-way resumes where
it stopped instead of duplicating issues."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from jira_backlog.domain.models import BacklogEpic
from jira_backlog.jira.fields import IssueSettings, epic_fields, story_fields


class IssueCreator(Protocol):
    def create_issue(self, fields: dict) -> str: ...


class CreatedState(Protocol):
    """Item key -> JIRA key of what already exists; ``save`` persists it."""

    def __contains__(self, item_key: object) -> bool: ...

    def __getitem__(self, item_key: str) -> str: ...

    def __setitem__(self, item_key: str, jira_key: str) -> None: ...

    def save(self) -> None: ...


@dataclass(frozen=True)
class PublishResult:
    item_key: str
    summary: str
    jira_key: str
    created: bool


class DryRunCreator:
    """Stands in for JIRA: numbers each request and keeps its fields."""

    def __init__(self):
        self.requests: list[dict] = []

    def create_issue(self, fields: dict) -> str:
        self.requests.append(fields)
        return f"DRY-RUN-{len(self.requests)}"


def publish(
    backlog: Iterable[BacklogEpic],
    creator: IssueCreator,
    state: CreatedState,
    settings: IssueSettings,
    report: Callable[[PublishResult], None] = lambda result: None,
) -> list[PublishResult]:
    results: list[PublishResult] = []

    def ensure(item_key: str, summary: str, build_fields: Callable[[], dict]) -> str:
        result = _ensure(item_key, summary, build_fields, creator, state)
        results.append(result)
        report(result)
        return result.jira_key

    for epic in backlog:
        epic_key = ensure(epic.key, epic.summary, partial(epic_fields, epic, settings))
        for story in epic.stories:
            ensure(story.key, story.summary, partial(story_fields, story, epic_key, settings))
    return results


def _ensure(item_key, summary, build_fields, creator, state) -> PublishResult:
    """Creates the issue unless the state already has it; fields are only
    built for an issue that is actually created."""
    if item_key in state:
        return PublishResult(item_key, summary, state[item_key], created=False)
    jira_key = creator.create_issue(build_fields())
    state[item_key] = jira_key
    state.save()
    return PublishResult(item_key, summary, jira_key, created=True)
