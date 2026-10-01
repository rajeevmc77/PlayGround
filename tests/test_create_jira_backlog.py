"""create_jira_backlog.py end to end over a tiny specs folder: --dry-run
writes the request bodies without touching JIRA, --check verifies the project
and lists its assignees, and a real run creates issues and resumes."""

import json

import httpx
import pytest

import create_jira_backlog
from create_jira_backlog import main

EPICS = """# Epics

## Epic 10: Dashboard

| # | User story | Key acceptance criteria | Status |
| --- | --- | --- | --- |
| 1 | As a user, I want a dashboard, so I see news. | Counts; calendar. | Shipped |

## Epic 11: Ask

| # | User story | Key acceptance criteria | Status |
| --- | --- | --- | --- |
| 1 | As a user, I want to ask, so I find things. | Filters only. | Shipped |
"""
SPEC = """# Feature Specification: Dashboard Spec

**Input**: User description: "Formalize Epic 10."

### User Story 1 - See today (Priority: P1)

Narrative.
"""
CONFIG = """
[jira]
url = "https://x.atlassian.net"
username = "me@x.com"
project_key = "AUBM"

[issues]
labels = ["aot-pulse"]
"""
ENV = {"JIRA_API_TOKEN": "tok"}


@pytest.fixture
def layout(tmp_path):
    specs = tmp_path / "specs"
    (specs / "013-dashboard").mkdir(parents=True)
    (specs / "013-dashboard" / "spec.md").write_text(SPEC)
    (specs / "014-ask").mkdir()
    (specs / "014-ask" / "spec.md").write_text(SPEC.replace("Dashboard Spec", "Ask Spec"))
    (specs / "epics.md").write_text(EPICS)
    (tmp_path / "jira.toml").write_text(CONFIG)
    return tmp_path


def _args(layout, *extra):
    return [
        "--specs-dir", str(layout / "specs"),
        "--epics-file", str(layout / "specs" / "epics.md"),
        "--config", str(layout / "jira.toml"),
        "--state-file", str(layout / "state.json"),
        "--preview-file", str(layout / "preview.json"),
        *extra,
    ]  # fmt: skip


class FakeJira:
    def __init__(self, projects=("AUBM",)):
        self.issues, self.projects = [], projects

    def __call__(self, request):
        if request.url.path == "/rest/api/3/project/":
            return httpx.Response(200, json=[{"key": key, "name": key} for key in self.projects])
        if request.url.path == "/rest/api/3/user/assignable/search":
            return httpx.Response(200, json=[{"accountId": "712020:a", "displayName": "Rajeev"}])
        self.issues.append(json.loads(request.content)["fields"])
        return httpx.Response(201, json={"key": f"AUBM-{len(self.issues)}"})


def test_dry_run_writes_the_request_bodies_and_never_calls_jira(layout, capsys):
    def refuse(request):
        raise AssertionError("dry run must not call JIRA")

    code = main(_args(layout, "--dry-run"), ENV, httpx.MockTransport(refuse))

    preview = json.loads((layout / "preview.json").read_text())
    assert code == 0
    assert [p["fields"]["summary"] for p in preview] == [
        "Dashboard",
        "As a user, I want a dashboard",
        "Ask",
        "As a user, I want to ask",
    ]
    assert preview[1]["fields"]["parent"] == {"key": "DRY-RUN-1"}
    assert preview[0]["item_key"] == "E10"
    assert not (layout / "state.json").exists()
    assert "4 issues (2 epics, 2 stories)" in capsys.readouterr().out


def test_dry_run_needs_no_config_file(layout):
    (layout / "jira.toml").unlink()

    assert main(_args(layout, "--dry-run"), {}, None) == 0
    preview = json.loads((layout / "preview.json").read_text())
    assert preview[0]["fields"]["project"] == {"key": "AUBM"}


def test_dry_run_without_a_token_still_applies_the_file_s_issue_settings(layout):
    main(_args(layout, "--dry-run"), {}, None)

    preview = json.loads((layout / "preview.json").read_text())
    assert preview[0]["fields"]["labels"] == ["aot-pulse"]


def test_epic_option_limits_the_run_to_the_named_epics(layout):
    main(_args(layout, "--dry-run", "--epic", "11"), ENV, None)

    preview = json.loads((layout / "preview.json").read_text())
    assert [p["item_key"] for p in preview] == ["E11", "E11-S01"]


def test_publish_creates_every_issue_and_records_the_keys(layout, capsys):
    jira = FakeJira()

    code = main(_args(layout), ENV, httpx.MockTransport(jira))

    assert code == 0
    assert [f["issuetype"]["name"] for f in jira.issues] == ["Epic", "Story", "Epic", "Story"]
    assert jira.issues[0]["labels"] == ["aot-pulse"]
    state = json.loads((layout / "state.json").read_text())
    assert state == {"E10": "AUBM-1", "E10-S01": "AUBM-2", "E11": "AUBM-3", "E11-S01": "AUBM-4"}
    assert "created AUBM-1  E10  Dashboard" in capsys.readouterr().out


def test_a_second_publish_creates_nothing_new(layout, capsys):
    main(_args(layout), ENV, httpx.MockTransport(FakeJira()))
    jira = FakeJira()

    main(_args(layout), ENV, httpx.MockTransport(jira))

    assert jira.issues == []
    assert "exists  AUBM-1  E10" in capsys.readouterr().out


def test_check_confirms_the_project_and_lists_assignees(layout, capsys):
    code = main(_args(layout, "--check"), ENV, httpx.MockTransport(FakeJira()))

    out = capsys.readouterr().out
    assert code == 0
    assert "project AUBM found" in out
    assert "712020:a  Rajeev" in out


def test_check_fails_when_the_project_is_not_visible(layout, capsys):
    code = main(_args(layout, "--check"), ENV, httpx.MockTransport(FakeJira(projects=("OTHER",))))

    assert code == 1
    assert "project AUBM not found" in capsys.readouterr().err


def test_missing_credentials_exit_with_a_message(layout, capsys):
    assert main(_args(layout), {}, None) == 2
    assert "api_token" in capsys.readouterr().err


def test_a_jira_error_exits_with_its_message(layout, capsys):
    def reject(request):
        return httpx.Response(400, json={"errors": {"issuetype": "Specify a valid issue type"}})

    assert main(_args(layout), ENV, httpx.MockTransport(reject)) == 1
    assert "Specify a valid issue type" in capsys.readouterr().err


def test_default_paths_anchor_to_the_project_root():
    root = create_jira_backlog.PROJECT_ROOT

    assert (root / "src" / "create_jira_backlog.py").is_file()
    assert create_jira_backlog.DEFAULT_SPECS_DIR == root / "AOTPulse Specs"
