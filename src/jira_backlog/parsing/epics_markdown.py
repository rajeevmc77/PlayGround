"""Reads "AOT BidHub — Epics & User Stories.md": each "## Epic N: Title"
heading, its optional italic scope note, and its user-story table rows."""

import re

from jira_backlog.domain.models import EpicTableRow, ParsedEpic
from jira_backlog.parsing.blocks import split_blocks

_EPIC_HEADING = re.compile(r"^## Epic (\d+):\s*(.+?)\s*$")
_NOTE = re.compile(r"^\*(?!\*)(.+)\*$")


def parse_epics(text: str) -> list[ParsedEpic]:
    return [_parse_block(block) for block in _epic_blocks(text.splitlines())]


def _epic_blocks(lines: list[str]) -> list[list[str]]:
    return split_blocks(lines, _EPIC_HEADING, _ends_epic)


def _ends_epic(line: str) -> bool:
    return line.startswith("## ") or line.strip() == "---"


def _parse_block(block: list[str]) -> ParsedEpic:
    heading = _EPIC_HEADING.match(block[0])
    body = [line.strip() for line in block[1:]]
    rows = tuple(row for row in map(_table_row, body) if row)
    return ParsedEpic(int(heading.group(1)), heading.group(2), _scope_note(body), rows)


def _scope_note(body: list[str]) -> str | None:
    """The epic's italic note, e.g. *Not in the original spec-kit scope ...*"""
    notes = [match.group(1).strip() for match in map(_NOTE.match, body) if match]
    return notes[0] if notes else None


def _table_row(line: str) -> EpicTableRow | None:
    if not line.startswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if len(cells) != 4 or not cells[0].isdigit():
        return None
    return EpicTableRow(int(cells[0]), cells[1], cells[2], cells[3])
