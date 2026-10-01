"""The epics document and the spec-kit spec.md files are the backlog's two
sources; these tests pin how each is read into plain records."""

import pytest

from jira_backlog.parsing.epics_markdown import parse_epics
from jira_backlog.parsing.spec_markdown import parse_spec

EPICS_DOC = """# AOT BidHub — Epics & User Stories

Intro paragraph that is not an epic.

## Epic 1: Authentication & Access Control

| # | User story | Key acceptance criteria | Status |
| --- | --- | --- | --- |
| 1 | As any AOT employee, I sign in. (FR-AUTH-1) | ID-token flow; `app_users` lookup. | Shipped |
| 2 | As an Admin, I want logins recorded, so access is auditable. | Writes `audit_log`. | Shipped |

## Epic 10: Dashboard, Global Search & Notifications

*Not in the original spec-kit scope — built against screenshots.*

| # | User story | Key acceptance criteria | Status |
| --- | --- | --- | --- |
| 1 | As a user, I want a dashboard, so I see news. | Counts reflect the lifecycle. | Shipped |

---

Trailing note that belongs to no epic.
"""


def test_parse_epics_reads_number_title_and_rows():
    epics = parse_epics(EPICS_DOC)

    assert [(e.number, e.title) for e in epics] == [
        (1, "Authentication & Access Control"),
        (10, "Dashboard, Global Search & Notifications"),
    ]
    first = epics[0].rows[0]
    assert first.number == 1
    assert first.story.startswith("As any AOT employee")
    assert first.criteria == "ID-token flow; `app_users` lookup."
    assert first.status == "Shipped"
    assert len(epics[0].rows) == 2


def test_parse_epics_keeps_the_italic_scope_note_and_none_when_absent():
    epics = parse_epics(EPICS_DOC)

    assert epics[0].note is None
    assert epics[1].note == "Not in the original spec-kit scope — built against screenshots."


def test_parse_epics_of_empty_text_is_empty():
    assert parse_epics("") == []


def test_parse_epics_ignores_a_table_row_with_a_non_numeric_index():
    doc = "## Epic 2: Admin\n\n| # | Story | Criteria | Status |\n| x | a | b | c |\n"

    assert parse_epics(doc)[0].rows == ()


SPEC_DOC = """# Feature Specification: Instant List Navigation (People Module Query Cache)

**Feature Branch**: `003-people-query-cache`

**Status**: Draft

**Input**: User description: "Make the People list instant."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Returning to the People list feels instant (Priority: P1) 🎯 MVP

A Bid Manager returns to the People list and it shows immediately.

**Why this priority**: It is the most visited list.

**Independent Test**: Open a person, go back, and confirm no spinner.

**Acceptance Scenarios**:

1. **Given** a loaded list, **When** the user returns, **Then** rows show at once.
2. **Given** stale data, **When** shown, **Then** it refreshes quietly.

---

### User Story 2 - Paging stays correct (Priority: P2)

Paging works.

**Acceptance Scenarios**:

1. **Given** page 2, **When** reloaded, **Then** page 2 shows.

### Edge Cases

- Something odd.

## Requirements *(mandatory)*

- **FR-001**: ignored.
"""


def test_parse_spec_reads_feature_header():
    spec = parse_spec("003-people-query-cache", SPEC_DOC)

    assert spec.folder == "003-people-query-cache"
    assert spec.title == "Instant List Navigation (People Module Query Cache)"
    assert spec.status == "Draft"
    assert spec.summary == "Make the People list instant."


def test_parse_spec_reads_each_user_story_with_its_sections():
    first, second = parse_spec("003", SPEC_DOC).stories

    assert (first.number, first.priority) == (1, "P1")
    assert first.title == "Returning to the People list feels instant"
    assert first.narrative == "A Bid Manager returns to the People list and it shows immediately."
    assert first.why == "It is the most visited list."
    assert first.independent_test == "Open a person, go back, and confirm no spinner."
    assert first.acceptance == (
        "**Given** a loaded list, **When** the user returns, **Then** rows show at once.",
        "**Given** stale data, **When** shown, **Then** it refreshes quietly.",
    )
    assert (second.number, second.priority, second.why) == (2, "P2", None)
    assert second.acceptance == ("**Given** page 2, **When** reloaded, **Then** page 2 shows.",)


def test_parse_spec_without_user_stories_has_none():
    spec = parse_spec("x", "# Feature Specification: Bare\n")

    assert spec.title == "Bare"
    assert (spec.status, spec.summary, spec.stories) == (None, None, ())


def test_parse_spec_rejects_a_document_without_a_feature_title():
    with pytest.raises(ValueError, match="Feature Specification"):
        parse_spec("x", "# Something else\n")


WRAPPED_SPEC = """# Feature Specification: Wrapped

### User Story 1 - Sign in (Priority: P1)

Any employee signs in
and lands on the module list.

**Why this priority**: Every story
depends on this gate.

**Acceptance Scenarios**:

1. **Given** an account,
   **When** they sign in, **Then** they reach the app.
2. **Given** no account, **When** they sign in, **Then** access is pending.
"""


def test_parse_spec_joins_hard_wrapped_paragraphs_and_scenarios():
    story = parse_spec("001", WRAPPED_SPEC).stories[0]

    assert story.narrative == "Any employee signs in and lands on the module list."
    assert story.why == "Every story depends on this gate."
    assert story.acceptance == (
        "**Given** an account, **When** they sign in, **Then** they reach the app.",
        "**Given** no account, **When** they sign in, **Then** access is pending.",
    )
