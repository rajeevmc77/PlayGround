"""The ``fields`` object of a JIRA create-issue request for a backlog epic or
story. A story is tied to its epic through ``parent`` (team-managed and current
company-managed projects) or, when configured, a legacy "Epic Link" field."""

from dataclasses import dataclass, field

from jira_backlog.domain.models import BacklogEpic, BacklogStory
from jira_backlog.output.adf import document


@dataclass(frozen=True)
class IssueSettings:
    project_key: str
    epic_issue_type: str = "Epic"
    story_issue_type: str = "Story"
    labels: tuple[str, ...] = ()
    epic_name_field: str | None = None
    epic_link_field: str | None = None
    assignee_account_id: str | None = None
    priorities: dict[str, str] = field(default_factory=dict)


def epic_fields(epic: BacklogEpic, settings: IssueSettings) -> dict:
    fields = _common(settings, settings.epic_issue_type, epic.summary, epic.labels)
    fields["description"] = document(epic.sections)
    if settings.epic_name_field:
        fields[settings.epic_name_field] = epic.summary
    return fields


def story_fields(story: BacklogStory, epic_key: str, settings: IssueSettings) -> dict:
    fields = _common(settings, settings.story_issue_type, story.summary, story.labels)
    fields["description"] = document(story.sections)
    if settings.epic_link_field:
        fields[settings.epic_link_field] = epic_key
    else:
        fields["parent"] = {"key": epic_key}
    priority = settings.priorities.get(story.priority or "")
    if priority:
        fields["priority"] = {"name": priority}
    return fields


def _common(settings: IssueSettings, issue_type: str, summary: str, labels) -> dict:
    fields = {
        "project": {"key": settings.project_key},
        "issuetype": {"name": issue_type},
        "summary": summary,
        "labels": [*settings.labels, *labels],
    }
    if settings.assignee_account_id:
        fields["assignee"] = {"accountId": settings.assignee_account_id}
    return fields
