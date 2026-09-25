import re

from web_toc.domain.models import WebNode

_DIVISION_LETTER_RE = re.compile(r"Division\s+([A-Z])")
_HEADING_RE = re.compile(
    r"^(?P<heading>(?:Volume|Division|Part)\s+\S+|Notes to Part\s+\d+|\d+(?:\.\d+)+)"
)


def build_tree(nav_data: dict) -> WebNode:
    return WebNode(
        type="root",
        identifier="",
        citation="root",
        title="BC Building Code",
        path="/",
        children=[_convert(raw) for raw in nav_data["tree"]],
    )


def heading_for(title: str) -> str:
    """The literal heading words at the front of a nav title ("Part 1",
    "10.1.1.1", "Notes to Part 1"). The title itself stays verbatim - the
    web tab's sidebar labels are built from it."""
    match = _HEADING_RE.match(title.strip())
    return match.group("heading") if match else ""


def _identifier_for(raw: dict) -> str:
    number = str(raw.get("number", ""))
    if number or raw["type"] != "division":
        return number
    match = _DIVISION_LETTER_RE.search(raw.get("title", ""))
    return match.group(1) if match else ""


def _convert(raw: dict) -> WebNode:
    return WebNode(
        type=raw["type"],
        identifier=_identifier_for(raw),
        citation=raw["id"],
        title=raw.get("title", ""),
        path=raw.get("path", ""),
        children=[_convert(child) for child in raw.get("children", [])],
        heading=heading_for(raw.get("title", "")),
    )


def collect_citations(node: WebNode) -> set[str]:
    citations = {node.citation}
    for child in node.children:
        citations |= collect_citations(child)
    return citations
