"""publish creates each epic, then its stories under it, recording every
created key so a re-run (after a failure part-way) skips what already exists."""

import json

import pytest

from jira_backlog.application.publisher import DryRunCreator, publish
from jira_backlog.domain.models import BacklogEpic, BacklogStory
from jira_backlog.jira.fields import IssueSettings
from jira_backlog.output.state_file import JsonStateStore

SETTINGS = IssueSettings(project_key="AUBM")
STORY_A = BacklogStory("E01-S01", "Story A", ())
STORY_B = BacklogStory("E01-S02", "Story B", ())
BACKLOG = [
    BacklogEpic("E01", "Epic one", (), (STORY_A, STORY_B)),
    BacklogEpic("E02", "Epic two", (), ()),
]


class RecordingCreator:
    def __init__(self, fail_on=None):
        self.created, self.fail_on = [], fail_on

    def create_issue(self, fields):
        if fields["summary"] == self.fail_on:
            raise RuntimeError("boom")
        self.created.append(fields)
        return f"AUBM-{len(self.created)}"


class MemoryState(dict):
    def save(self):
        self.saved = dict(self)


def test_publish_creates_epics_then_their_stories_under_them():
    creator, state = RecordingCreator(), MemoryState()

    results = publish(BACKLOG, creator, state, SETTINGS)

    assert [f["summary"] for f in creator.created] == ["Epic one", "Story A", "Story B", "Epic two"]
    assert creator.created[1]["parent"] == {"key": "AUBM-1"}
    assert [(r.item_key, r.jira_key, r.created) for r in results] == [
        ("E01", "AUBM-1", True),
        ("E01-S01", "AUBM-2", True),
        ("E01-S02", "AUBM-3", True),
        ("E02", "AUBM-4", True),
    ]
    assert state.saved == {
        "E01": "AUBM-1",
        "E01-S01": "AUBM-2",
        "E01-S02": "AUBM-3",
        "E02": "AUBM-4",
    }


def test_publish_skips_items_already_in_the_state_and_links_to_the_known_epic():
    creator, state = RecordingCreator(), MemoryState({"E01": "AUBM-9", "E01-S01": "AUBM-10"})

    results = publish(BACKLOG, creator, state, SETTINGS)

    assert [f["summary"] for f in creator.created] == ["Story B", "Epic two"]
    assert creator.created[0]["parent"] == {"key": "AUBM-9"}
    assert (results[0].jira_key, results[0].created) == ("AUBM-9", False)


def test_publish_keeps_what_it_created_before_a_failure():
    state = MemoryState()

    with pytest.raises(RuntimeError):
        publish(BACKLOG, RecordingCreator(fail_on="Story B"), state, SETTINGS)

    assert state.saved == {"E01": "AUBM-1", "E01-S01": "AUBM-2"}


def test_publish_reports_each_result_as_it_goes():
    seen = []

    publish(BACKLOG[1:], RecordingCreator(), MemoryState(), SETTINGS, report=seen.append)

    assert [r.summary for r in seen] == ["Epic two"]


def test_publish_of_an_empty_backlog_creates_nothing():
    assert publish([], RecordingCreator(), MemoryState(), SETTINGS) == []


def test_dry_run_creator_numbers_issues_and_keeps_their_fields():
    creator = DryRunCreator()

    assert creator.create_issue({"summary": "a"}) == "DRY-RUN-1"
    assert creator.create_issue({"summary": "b"}) == "DRY-RUN-2"
    assert [f["summary"] for f in creator.requests] == ["a", "b"]


def test_json_state_store_round_trips_through_its_file(tmp_path):
    path = tmp_path / "state" / "jira.json"
    store = JsonStateStore(path)
    store["E01"] = "AUBM-1"
    store.save()

    assert json.loads(path.read_text()) == {"E01": "AUBM-1"}
    assert JsonStateStore(path)["E01"] == "AUBM-1"


def test_json_state_store_starts_empty_without_a_file(tmp_path):
    assert dict(JsonStateStore(tmp_path / "missing.json")) == {}
