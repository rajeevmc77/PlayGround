"""Rendering a backlog item as the JSON body JIRA's POST /rest/api/3/issue
takes: an Atlassian Document Format description plus the issue fields."""

from jira_backlog.domain.models import BacklogEpic, BacklogStory, Section
from jira_backlog.jira.fields import IssueSettings, epic_fields, story_fields
from jira_backlog.output.adf import document, inline


def test_inline_marks_bold_and_code_and_keeps_plain_text():
    assert inline("a **b** `c` d") == [
        {"type": "text", "text": "a "},
        {"type": "text", "text": "b", "marks": [{"type": "strong"}]},
        {"type": "text", "text": " "},
        {"type": "text", "text": "c", "marks": [{"type": "code"}]},
        {"type": "text", "text": " d"},
    ]


def test_inline_of_empty_text_is_empty():
    assert inline("") == []


def test_document_renders_heading_paragraph_and_lists():
    doc = document(
        [
            Section("Story", "Text."),
            Section("Criteria", items=("one",)),
            Section("Steps", items=("first",), ordered=True),
        ]
    )

    assert doc["type"] == "doc" and doc["version"] == 1
    kinds = [node["type"] for node in doc["content"]]
    assert kinds == ["heading", "paragraph", "heading", "bulletList", "heading", "orderedList"]
    assert doc["content"][0]["attrs"] == {"level": 3}
    item = doc["content"][3]["content"][0]
    assert item == {
        "type": "listItem",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}],
    }


def test_document_with_both_text_and_items_has_both():
    doc = document([Section("Spec", "Narrative.", ("scenario",))])

    assert [node["type"] for node in doc["content"]] == ["heading", "paragraph", "bulletList"]


def test_document_of_no_sections_is_an_empty_paragraph():
    assert document([])["content"] == [{"type": "paragraph", "content": []}]


EPIC = BacklogEpic("E01", "Authentication", (Section("Scope note", "Note."),), ())
STORY = BacklogStory("E01-S01", "As X, I want Y", (), ("shipped",), "P1")


def test_epic_fields_use_project_type_summary_and_base_labels():
    fields = epic_fields(EPIC, IssueSettings(project_key="AUBM", labels=("aot-pulse",)))

    assert fields["project"] == {"key": "AUBM"}
    assert fields["issuetype"] == {"name": "Epic"}
    assert fields["summary"] == "Authentication"
    assert fields["labels"] == ["aot-pulse"]
    assert fields["description"]["type"] == "doc"
    assert "assignee" not in fields


def test_epic_fields_fill_the_epic_name_field_when_configured():
    settings = IssueSettings(project_key="AUBM", epic_name_field="customfield_10011")

    assert epic_fields(EPIC, settings)["customfield_10011"] == "Authentication"


def test_story_fields_link_to_the_epic_through_parent_by_default():
    fields = story_fields(STORY, "AUBM-7", IssueSettings(project_key="AUBM", labels=("aot-pulse",)))

    assert fields["issuetype"] == {"name": "Story"}
    assert fields["parent"] == {"key": "AUBM-7"}
    assert fields["labels"] == ["aot-pulse", "shipped"]
    assert "priority" not in fields


def test_story_fields_use_the_epic_link_field_when_configured():
    settings = IssueSettings(project_key="AUBM", epic_link_field="customfield_10014")

    fields = story_fields(STORY, "AUBM-7", settings)

    assert fields["customfield_10014"] == "AUBM-7"
    assert "parent" not in fields


def test_story_fields_map_priority_and_assignee_when_configured():
    settings = IssueSettings(
        project_key="AUBM", priorities={"P1": "High"}, assignee_account_id="712020:abc"
    )

    fields = story_fields(STORY, "AUBM-7", settings)

    assert fields["priority"] == {"name": "High"}
    assert fields["assignee"] == {"accountId": "712020:abc"}


def test_story_fields_skip_a_priority_with_no_mapping():
    settings = IssueSettings(project_key="AUBM", priorities={"P2": "Medium"})

    assert "priority" not in story_fields(STORY, "AUBM-7", settings)
