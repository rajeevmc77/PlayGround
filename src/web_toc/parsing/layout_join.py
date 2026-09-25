"""Joins the layout pass's measurements (one layout dict per saved page, see
layout_script.py) onto the tree built from the content JSON: every node it
can find gets a `location` - {page_file, xpath, bbox} - and body-text nodes
get the text the site actually renders, in place of the JSON's unresolved
[REF:...] tokens.

A node lives on the page of its nearest ancestor-or-self that has a saved
page (subsections/articles are cut from their section's page). Match rules:
- the site's own element id == node citation (sentences, clauses,
  subclauses, tables, notes, ...);
- Row/Cell by position inside their table's grid - they have no ids, and the
  JSON rows/cells line up 1:1 with the rendered tr/td|th;
- part/section/subsection/article by their heading number against the
  page's h1-h6 text (headings have no ids);
- images by `src` on their owner's page.
Pure: no file or browser I/O.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterator

from web_toc.domain.models import WebImage, WebNode
from web_toc.parsing.page_html import ASSET_PREFIX

PAGES_DIR = "web_pages"
RENDERED_TEXT_TYPES = frozenset({"Cell", "Sentence", "Clause", "Subclause", "Note"})
HEADING_TYPES = frozenset({"part", "section", "subsection", "article"})


class GridMismatch(ValueError):
    """A table's rendered rows/cells don't line up with its content JSON."""


def _location(page: str, entry: dict) -> dict:
    return {"page_file": f"{PAGES_DIR}/{page}.html", "xpath": entry["xpath"], "bbox": entry["bbox"]}


def _place(node: WebNode, page: str, entry: dict | None) -> None:
    if entry is None:
        return
    node.location = _location(page, entry)
    if node.type in RENDERED_TEXT_TYPES:
        node.content = entry["text"]


def _heading_entry(node: WebNode, layout: dict) -> dict | None:
    if node.type not in HEADING_TYPES or not node.heading:
        return None
    pattern = re.compile(rf"^(?:Section\s+)?{re.escape(node.heading)}(?!\d|\.\d)")
    return next((h for h in layout.get("headings", []) if pattern.match(h["text"])), None)


def _check_grid(table: WebNode, grid: list[dict]) -> None:
    if len(grid) != len(table.children):
        raise GridMismatch(
            f"{table.citation}: {len(grid)} rendered rows, {len(table.children)} in JSON"
        )
    for index, (row, rendered) in enumerate(zip(table.children, grid, strict=True)):
        if len(row.children) != len(rendered["cells"]):
            raise GridMismatch(f"{table.citation}: row {index + 1} cell count differs")


def _place_grid(table: WebNode, page: str, layout: dict) -> None:
    grid = layout.get("tables", {}).get(table.citation)
    if grid is None:
        return
    _check_grid(table, grid)
    for row, rendered in zip(table.children, grid, strict=True):
        _place(row, page, rendered)
        for cell, cell_entry in zip(row.children, rendered["cells"], strict=True):
            _place(cell, page, cell_entry)


def _nodes_with_page(
    node: WebNode, page: str | None, page_citations: set[str]
) -> Iterator[tuple[WebNode, str | None]]:
    page = node.citation if node.citation in page_citations else page
    yield node, page
    for child in node.children:
        yield from _nodes_with_page(child, page, page_citations)


def _place_node(node: WebNode, page: str, layout: dict) -> None:
    entry = layout.get("elements", {}).get(node.citation) or _heading_entry(node, layout)
    _place(node, page, entry)
    if node.type == "Table":
        _place_grid(node, page, layout)


def _place_image(image: WebImage, page: str, layout: dict) -> None:
    src = f"{ASSET_PREFIX}/{image.src}.jpg"
    entry = next((img for img in layout.get("images", []) if img["src"] == src), None)
    if entry is not None:
        image.location = _location(page, entry)


def _place_nodes(
    root: WebNode, layouts: dict[str, dict], page_citations: set[str]
) -> dict[str, str]:
    """Places every node on a measured page; returns {citation: page}."""
    page_of: dict[str, str] = {}
    for node, page in _nodes_with_page(root, None, page_citations):
        if page not in layouts:
            continue
        page_of[node.citation] = page
        if node.type not in ("Row", "Cell"):  # placed with their table
            _place_node(node, page, layouts[page])
    return page_of


def join_layout(
    root: WebNode, images: list[WebImage], layouts: dict[str, dict], page_citations: set[str]
) -> None:
    page_of = _place_nodes(root, layouts, page_citations)
    for image in images:
        page = page_of.get(image.owner_citation)
        if page is not None:
            _place_image(image, page, layouts[page])


def _walk(node: WebNode) -> Iterator[WebNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _typed_locations(root: WebNode, images: list[WebImage]) -> Iterator[tuple[str, dict | None]]:
    yield from ((node.type, node.location) for node in _walk(root) if node.type != "root")
    yield from (("Image", image.location) for image in images)


def location_report(root: WebNode, images: list[WebImage]) -> dict[str, dict[str, int]]:
    """{node type (or "Image"): {"located": n, "unlocated": n}}."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for type_, location in _typed_locations(root, images):
        counts[type_]["located" if location else "unlocated"] += 1
    return {t: {"located": c["located"], "unlocated": c["unlocated"]} for t, c in counts.items()}
