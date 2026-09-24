"""Walks one section/appendix/spectables/front-matter-article content JSON
for {"type": "table", ...} nodes, wherever they're nested, and builds a
Table -> Row -> Cell WebNode subtree per table found - mirroring
mo_toc.parsing.table_extractor's Table -> Row -> Cell shape. Simpler than
that PDF pipeline in the same way image_extractor.py is: a table's own id
already encodes its full ancestor chain, so owner resolution is the same
strip-and-match used for figures, not a bbox/page comparison.
"""

from web_toc.domain.models import WebNode
from web_toc.parsing.owner_resolution import resolve_owner


def _cell_text(cell: dict) -> str:
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


def _row_node(table_citation: str, row_i: int, row: dict) -> WebNode:
    identifier = f"row{row_i + 1}"
    row_citation = f"{table_citation}-{identifier}"
    cells = [
        _cell_node(row_citation, col_i, cell) for col_i, cell in enumerate(row.get("cells", []))
    ]
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
        children=[_row_node(citation, i, row) for i, row in enumerate(all_rows)],
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


def _citation_index(node: WebNode, index: dict[str, WebNode]) -> dict[str, WebNode]:
    index[node.citation] = node
    for child in node.children:
        _citation_index(child, index)
    return index


def attach_tables(root: WebNode, owned_tables: list[tuple[str, WebNode]]) -> None:
    index = _citation_index(root, {})
    for owner_citation, table_node in owned_tables:
        owner = index.get(owner_citation)
        if owner is not None:
            owner.children.append(table_node)
