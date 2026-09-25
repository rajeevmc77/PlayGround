"""Walks a part/division appendix content JSON for the site's
{"type": "application_note", "number": "1.1.1.1.(3)", ...} entries and builds
one Note WebNode per note - the web counterpart of the PDF's
"A-1.1.1.1.(3) ..." Note nodes. Owner resolution is the same strip-and-match
used for figures and tables."""

from web_toc.domain.models import WebNode
from web_toc.parsing.owner_resolution import resolve_owner

_NON_TEXT_TYPES = frozenset({"table", "figure"})


def _walk_notes(node):
    if isinstance(node, dict):
        if node.get("type") == "application_note":
            yield node
        for value in node.values():
            yield from _walk_notes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_notes(item)


def _dict_text_parts(node: dict):
    if node.get("type") in _NON_TEXT_TYPES:
        return
    if isinstance(node.get("content"), str):
        yield node["content"]
    for key in ("content", "lists", "items"):
        yield from _text_parts(node.get(key))


def _text_parts(node):
    if isinstance(node, dict):
        yield from _dict_text_parts(node)
    elif isinstance(node, list):
        for item in node:
            yield from _text_parts(item)


def _note_node(note: dict) -> WebNode:
    number = note.get("number", "")
    identifier = f"A-{number}" if number else ""
    return WebNode(
        type="Note",
        identifier=identifier,
        citation=note["id"],
        title=note.get("title", ""),
        path="",
        content=" ".join(_text_parts(note.get("content", []))).strip(),
        heading=identifier,
    )


def extract_notes(
    content: dict, citations: set[str], fallback_citation: str
) -> list[tuple[str, WebNode]]:
    return [
        (resolve_owner(note["id"], citations, fallback_citation), _note_node(note))
        for note in _walk_notes(content)
        if note.get("id")
    ]
