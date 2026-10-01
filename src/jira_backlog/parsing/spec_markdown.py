"""Reads a spec-kit spec.md: the feature title/status/input line and every
"### User Story N - Title (Priority: Pn)" block with its labelled sections."""

import re

from jira_backlog.domain.models import SpecFeature, SpecStory
from jira_backlog.parsing.blocks import split_blocks

_TITLE = re.compile(r"^# Feature Specification:\s*(.+?)\s*$", re.MULTILINE)
_STATUS = re.compile(r"^\*\*Status\*\*:\s*(.+?)\s*$", re.MULTILINE)
_INPUT = re.compile(r'^\*\*Input\*\*:\s*(?:User description:\s*)?"?(.+?)"?\s*$', re.MULTILINE)
_STORY = re.compile(r"^### User Story (\d+) - (.+?)(?: \(Priority: (P\d)\).*)?$")
_LABELLED = re.compile(r"^\*\*(Why this priority|Independent Test)\*\*:\s*(.+)$")
_SCENARIO = re.compile(r"^\d+\.\s+(.+)$")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n|\n(?=\d+\.\s)")


def parse_spec(folder: str, text: str) -> SpecFeature:
    title = _TITLE.search(text)
    if not title:
        raise ValueError(f"{folder}: no '# Feature Specification:' title")
    stories = tuple(_parse_story(block) for block in _story_blocks(text.splitlines()))
    return SpecFeature(folder, title.group(1), _first(_STATUS, text), _first(_INPUT, text), stories)


def _first(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _story_blocks(lines: list[str]) -> list[list[str]]:
    return split_blocks(lines, _STORY, lambda line: line.startswith("#"))


def _paragraphs(lines: list[str]) -> list[str]:
    """Hard-wrapped lines joined back up; a blank line or a "N." item ends one."""
    text = "\n".join("" if line.strip() == "---" else line.strip() for line in lines)
    return [" ".join(chunk.split()) for chunk in _PARAGRAPH_BREAK.split(text) if chunk.strip()]


def _parse_story(block: list[str]) -> SpecStory:
    heading = _STORY.match(block[0])
    body = _paragraphs(block[1:])
    labelled = dict(_matches(_LABELLED, body))
    narrative = next(iter(_plain_paragraphs(body)), "")
    return SpecStory(
        number=int(heading.group(1)),
        title=heading.group(2).strip(),
        priority=heading.group(3),
        narrative=narrative,
        why=labelled.get("Why this priority"),
        independent_test=labelled.get("Independent Test"),
        acceptance=tuple(scenario for (scenario,) in _matches(_SCENARIO, body)),
    )


def _matches(pattern: re.Pattern, paragraphs: list[str]) -> list[tuple]:
    return [match.groups() for match in map(pattern.match, paragraphs) if match]


def _plain_paragraphs(paragraphs: list[str]) -> list[str]:
    """Paragraphs that are neither a bold-labelled section nor a numbered item."""
    return [p for p in paragraphs if not p.startswith("**") and not _SCENARIO.match(p)]
