"""build_backlog joins the epics document with the spec-kit specs: each epic
carries its own rows as stories plus, where a spec adds stories the epics
document never listed (the 002-012 enhancements), those too."""

import pytest

from jira_backlog.domain.backlog import EpicSpecLinks, build_backlog, story_summary
from jira_backlog.domain.models import EpicTableRow, ParsedEpic, SpecFeature, SpecStory


def _spec_story(number, title="Paging stays correct", priority="P1"):
    return SpecStory(number, title, priority, "Narrative.", "Why.", "Test it.", ("**Given** a,",))


SPECS = [
    SpecFeature("001-aot-bidhub", "AOT BidHub", "Draft", "Phase 1.", (_spec_story(1, "Sign in"),)),
    SpecFeature("003-people-query-cache", "People Cache", "Draft", None, (_spec_story(2),)),
    SpecFeature("013-dashboard", "Dashboard", "Draft", "Formalize Epic 10.", (_spec_story(1),)),
]
ROW = EpicTableRow(
    3, "As a Bid Manager, I want a checklist, so gates are tracked. (FR-BID-2)", "A; B", "Shipped"
)
EPICS = [
    ParsedEpic(4, "Bids", None, (ROW,)),
    ParsedEpic(10, "Dashboard", "Not in scope.", ()),
]
LINKS = {
    4: EpicSpecLinks(context=("001", 1), extra_stories=("003",)),
    10: EpicSpecLinks(context=("013", None)),
}


def _section(item, heading):
    return next(s for s in item.sections if s.heading == heading)


def test_each_epic_becomes_a_backlog_epic_in_document_order():
    epics = build_backlog(EPICS, SPECS, LINKS)

    assert [(e.key, e.summary) for e in epics] == [("E04", "Bids"), ("E10", "Dashboard")]


def test_epic_row_becomes_a_story_with_criteria_requirements_and_status():
    story = build_backlog(EPICS, SPECS, LINKS)[0].stories[0]

    assert story.key == "E04-S03"
    assert story.summary == "As a Bid Manager, I want a checklist"
    assert _section(story, "User story").text.startswith("As a Bid Manager")
    assert _section(story, "Acceptance criteria").items == ("A", "B")
    assert _section(story, "Requirements").text == "FR-BID-2"
    assert _section(story, "Status").text == "Shipped"
    assert story.labels == ("shipped",)
    assert story.priority is None


def test_epic_row_without_requirement_refs_has_no_requirements_section():
    row = EpicTableRow(1, "As X, I want Y.", "Z", "Shipped")
    story = build_backlog([ParsedEpic(2, "Admin", None, (row,))], SPECS, {})[0].stories[0]

    assert "Requirements" not in [s.heading for s in story.sections]


def test_extra_spec_stories_follow_the_epic_rows_with_spec_priority_and_label():
    story = build_backlog(EPICS, SPECS, LINKS)[0].stories[1]

    assert story.key == "S003-US2"
    assert story.summary == "People Cache — Paging stays correct"
    assert story.priority == "P1"
    assert story.labels == ("spec-003",)
    assert _section(story, "Acceptance scenarios").ordered is True
    assert _section(story, "Source").text == "AOTPulse Specs/003-people-query-cache/spec.md"


def test_spec_story_without_optional_sections_omits_them():
    bare = SpecStory(1, "Bare", None, "Only a narrative.", None, None, ())
    specs = [SpecFeature("003-x", "X", None, None, (bare,))]
    links = {4: EpicSpecLinks(extra_stories=("003",))}

    story = build_backlog(EPICS[:1], specs, links)[0].stories[1]

    assert [s.heading for s in story.sections] == ["User story", "Source"]
    assert story.priority is None


def test_epic_describes_the_single_spec_story_it_formalizes():
    epic = build_backlog(EPICS, SPECS, LINKS)[0]

    spec = _section(epic, "Specification: AOT BidHub — User Story 1: Sign in")
    assert spec.text == "Narrative."
    assert spec.items == ("**Given** a,",)
    assert _section(epic, "Related specifications").items == (
        "People Cache (AOTPulse Specs/003-people-query-cache/spec.md)",
    )


def test_epic_lists_a_whole_spec_and_keeps_the_scope_note():
    epic = build_backlog(EPICS, SPECS, LINKS)[1]

    assert _section(epic, "Scope note").text == "Not in scope."
    whole = _section(epic, "Specification: Dashboard")
    assert whole.text == "Formalize Epic 10."
    assert whole.items == ("User Story 1 (P1): Paging stays correct",)


def test_epic_without_links_has_only_its_rows():
    epic = build_backlog([ParsedEpic(9, "Docs", None, (ROW,))], SPECS, {})[0]

    assert [s.key for s in epic.stories] == ["E09-S03"]
    assert [s.heading for s in epic.sections] == []


def test_a_link_to_a_missing_spec_is_an_error():
    links = {4: EpicSpecLinks(extra_stories=("099",))}

    with pytest.raises(ValueError, match="099"):
        build_backlog(EPICS[:1], SPECS, links)


def test_a_link_to_a_missing_spec_story_is_an_error():
    links = {4: EpicSpecLinks(context=("001", 7))}

    with pytest.raises(ValueError, match="User Story 7"):
        build_backlog(EPICS[:1], SPECS, links)


@pytest.mark.parametrize(
    ("story", "expected"),
    [
        ("As X, I want Y, so that Z.", "As X, I want Y"),
        (
            "As X, I sign in (no password) so I reach Z. (FR-AUTH-1)",
            "As X, I sign in (no password)",
        ),
        ("As the system, I want time synced.", "As the system, I want time synced"),
        (
            "As X, I want it to say so plainly, so data is clear.",
            "As X, I want it to say so plainly",
        ),
        ("", ""),
    ],
)
def test_story_summary_keeps_the_want_clause(story, expected):
    assert story_summary(story) == expected


def test_story_summary_is_capped_at_a_word_boundary():
    summary = story_summary("word " * 80)

    assert len(summary) <= 250
    assert summary.endswith("word…")
