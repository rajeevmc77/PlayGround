"""Atlassian Document Format (the rich-text JSON JIRA Cloud's v3 API takes for
a description), built from description Sections. Inline ``**bold**`` and
`` `code` `` from the Markdown sources become strong/code marks."""

import re
from collections.abc import Iterable

from jira_backlog.domain.models import Section

_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")


def document(sections: Iterable[Section]) -> dict:
    content = [node for section in sections for node in _section(section)]
    return {"type": "doc", "version": 1, "content": content or [_paragraph("")]}


def inline(text: str) -> list[dict]:
    nodes, position = [], 0
    for match in _INLINE.finditer(text):
        nodes += _plain(text[position : match.start()])
        mark = "strong" if match.group(1) is not None else "code"
        nodes.append(
            {"type": "text", "text": match.group(1) or match.group(2), "marks": [{"type": mark}]}
        )
        position = match.end()
    return nodes + _plain(text[position:])


def _plain(text: str) -> list[dict]:
    return [{"type": "text", "text": text}] if text else []


def _section(section: Section) -> list[dict]:
    heading = {"type": "heading", "attrs": {"level": 3}, "content": inline(section.heading)}
    nodes = [heading]
    if section.text:
        nodes.append(_paragraph(section.text))
    if section.items:
        nodes.append(_list(section.items, section.ordered))
    return nodes


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": inline(text)}


def _list(items: Iterable[str], ordered: bool) -> dict:
    entries = [{"type": "listItem", "content": [_paragraph(item)]} for item in items]
    return {"type": "orderedList" if ordered else "bulletList", "content": entries}
