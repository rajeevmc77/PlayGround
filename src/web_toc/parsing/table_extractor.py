"""Walks one section/appendix/spectables/front-matter-article content JSON
for {"type": "table", ...} nodes, wherever they're nested, and builds a
Table -> Row -> Cell WebNode subtree per table found - mirroring
mo_toc.parsing.table_extractor's Table -> Row -> Cell shape. Simpler than
that PDF pipeline in the same way image_extractor.py is: a table's own id
already encodes its full ancestor chain, so owner resolution is the same
strip-and-match used for figures, not a bbox/page comparison.
"""

from web_toc.domain.models import WebNode
from web_toc.parsing.owner_resolution import attach_owned_nodes, resolve_owner


def _cell_text(cell: dict) -> str:
    if isinstance(cell.get("content"), str):  # some revision entries give plain text
        return cell["content"].strip()
    return " ".join(
        part.get("value", "") for part in cell.get("content", []) if part.get("type") == "text"
    ).strip()


def _cell_node(row_citation: str, col_i: int, cell: dict) -> WebNode:
    identifier = f"col{col_i + 1}"
    return WebNode(
        type="Cell",
        identifier=identifier,
        citation=f"{row_citation}-{identifier}",
        title="",
        path="",
        content=_cell_text(cell),
    )


_PLACEHOLDER: dict = {"content": []}


def _span(cell: dict, key: str) -> int:
    return max(1, int(cell.get(key) or 1))


def _still_covered_from(covered: dict[int, int], col: int) -> bool:
    return any(rows_left > 0 for c, rows_left in covered.items() if c >= col)


def _expand_row(cells: list[dict], covered: dict[int, int]) -> list[dict]:
    """One row's cells with an empty placeholder at every position a span
    covers. `covered` maps column -> rows below still covered by a rowspan
    from above; it's consumed and refilled as the row is laid out."""
    out, queue, col = [], list(cells), 0
    while queue or _still_covered_from(covered, col):
        if covered.get(col, 0) > 0:
            covered[col] -= 1
            out.append(_PLACEHOLDER)
            col += 1
            continue
        cell = queue.pop(0)
        width = _span(cell, "colspan")
        out.extend([cell] + [_PLACEHOLDER] * (width - 1))
        for spanned in range(col, col + width):
            covered[spanned] = _span(cell, "rowspan") - 1
        col += width
    return out


def _expand_spans(rows: list[dict]) -> list[list[dict]]:
    """The site's JSON lists only the cells that start in a row; the PDF grid
    keeps an empty cell wherever a row/column span covers a position. Laying
    the web grid out the same way keeps both sides' columns aligned."""
    covered: dict[int, int] = {}
    return [_expand_row(row.get("cells", []), covered) for row in rows]


def _row_node(table_citation: str, row_i: int, cells_in_row: list[dict]) -> WebNode:
    identifier = f"row{row_i + 1}"
    row_citation = f"{table_citation}-{identifier}"
    cells = [_cell_node(row_citation, col_i, cell) for col_i, cell in enumerate(cells_in_row)]
    return WebNode(
        type="Row",
        identifier=identifier,
        citation=row_citation,
        title="",
        path="",
        children=cells,
    )


def _table_node(table: dict) -> WebNode:
    citation = table["id"]
    structure = table.get("structure", {})
    all_rows = structure.get("header_rows", []) + structure.get("body_rows", [])
    return WebNode(
        type="Table",
        identifier=citation.rsplit(".", 1)[-1],
        citation=citation,
        title=table.get("title", ""),
        path="",
        children=[_row_node(citation, i, cells) for i, cells in enumerate(_expand_spans(all_rows))],
    )


def _walk_tables(node):
    if isinstance(node, dict):
        if node.get("type") == "table":
            yield node
        for value in node.values():
            yield from _walk_tables(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_tables(item)


def extract_tables(
    content: dict, citations: set[str], fallback_citation: str
) -> list[tuple[str, WebNode]]:
    owned_tables = []
    for table in _walk_tables(content):
        table_id = table.get("id")
        if table_id is None:
            continue
        owner = resolve_owner(table_id, citations, fallback_citation)
        owned_tables.append((owner, _table_node(table)))
    return owned_tables


def table_row_counts(content) -> dict[str, int]:
    """Rows each table must have once rendered (header + body) - the target
    the scraper keeps lazy-loading a long table's rows up to."""
    counts = {}
    for table in _walk_tables(content):
        if table.get("id") is None:
            continue
        structure = table.get("structure", {})
        counts[table["id"]] = len(structure.get("header_rows", [])) + len(
            structure.get("body_rows", [])
        )
    return counts


def attach_tables(root: WebNode, owned_tables: list[tuple[str, WebNode]]) -> None:
    attach_owned_nodes(root, owned_tables)
