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


def _paired_cells(cells: list[WebNode], rendered: list[dict]) -> list[tuple[WebNode, dict]]:
    """JSON cells paired with rendered cells, left to right. In header rows
    the JSON carries empty placeholders for span-covered positions that the
    site doesn't render; those are skipped while there are more JSON cells
    than rendered ones. [] unless every non-empty JSON cell gets a partner -
    a cell with content is never paired by guesswork."""
    if len(cells) == len(rendered):
        return list(zip(cells, rendered, strict=True))
    pairs = _pair_skipping_placeholders(cells, rendered)
    complete = len(pairs) == len(rendered) and _every_content_cell_paired(cells, pairs)
    return pairs if complete else []


def _every_content_cell_paired(cells: list[WebNode], pairs: list[tuple[WebNode, dict]]) -> bool:
    paired = {id(cell) for cell, _ in pairs}
    return not any(cell.content for cell in cells if id(cell) not in paired)


def _is_placeholder(cell: WebNode, next_rendered: dict, surplus: bool) -> bool:
    return surplus and not cell.content and bool(next_rendered["text"])


def _pair_skipping_placeholders(
    cells: list[WebNode], rendered: list[dict]
) -> list[tuple[WebNode, dict]]:
    pairs: list[tuple[WebNode, dict]] = []
    for index, cell in enumerate(cells):
        taken = len(pairs)
        if taken == len(rendered):
            break
        surplus = len(cells) - index > len(rendered) - taken
        if not _is_placeholder(cell, rendered[taken], surplus):
            pairs.append((cell, rendered[taken]))
    return pairs


def _check_row_count(table: WebNode, grid: list[dict]) -> None:
    if len(grid) != len(table.children):
        raise GridMismatch(
            f"{table.citation}: {len(grid)} rendered rows, {len(table.children)} in JSON"
        )


def _place_grid(table: WebNode, page: str, layout: dict) -> list[str]:
    """Places rows/cells; returns the rows whose cells couldn't be paired."""
    grid = layout.get("tables", {}).get(table.citation)
    if grid is None:
        return []
    _check_row_count(table, grid)
    misaligned = []
    for index, (row, rendered) in enumerate(zip(table.children, grid, strict=True)):
        _place(row, page, rendered)
        pairs = _paired_cells(row.children, rendered["cells"])
        if row.children and not pairs:
            misaligned.append(f"{table.citation} row {index + 1}")
        for cell, cell_entry in pairs:
            _place(cell, page, cell_entry)
    return misaligned


def _nodes_with_page(
    node: WebNode, page: str | None, page_citations: set[str]
) -> Iterator[tuple[WebNode, str | None]]:
    page = node.citation if node.citation in page_citations else page
    yield node, page
    for child in node.children:
        yield from _nodes_with_page(child, page, page_citations)


def _place_node(node: WebNode, page: str, layout: dict) -> list[str]:
    entry = layout.get("elements", {}).get(node.citation) or _heading_entry(node, layout)
    _place(node, page, entry)
    return _place_grid(node, page, layout) if node.type == "Table" else []


def _place_image(image: WebImage, page: str, layout: dict) -> None:
    src = f"{ASSET_PREFIX}/{image.src}.jpg"
    entry = next((img for img in layout.get("images", []) if img["src"] == src), None)
    if entry is not None:
        image.location = _location(page, entry)


def _place_nodes(
    root: WebNode, layouts: dict[str, dict], page_citations: set[str]
) -> tuple[dict[str, str], list[str]]:
    """Places every node on a measured page; returns ({citation: page},
    misaligned table rows)."""
    page_of: dict[str, str] = {}
    misaligned: list[str] = []
    for node, page in _nodes_with_page(root, None, page_citations):
        if page not in layouts:
            continue
        page_of[node.citation] = page
        if node.type not in ("Row", "Cell"):  # placed with their table
            misaligned += _place_node(node, page, layouts[page])
    return page_of, misaligned


def join_layout(
    root: WebNode, images: list[WebImage], layouts: dict[str, dict], page_citations: set[str]
) -> list[str]:
    """Returns the table rows ("<table citation> row N") whose cells could
    not be paired with the rendered ones and were left unlocated."""
    page_of, misaligned = _place_nodes(root, layouts, page_citations)
    for image in images:
        page = page_of.get(image.owner_citation)
        if page is not None:
            _place_image(image, page, layouts[page])
    return misaligned


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
