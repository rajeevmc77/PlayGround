"""Rolls a pass/fail comparison status up the PDF tree, joining to the web
tree/images on the shared unified_number key both sides already carry (the
same join the viewer's Both tab uses - see shared/numbering.py). A node
passes only if its own text matches, every image it owns matches, and every
child passes; a unified_number with no counterpart on the other side always
fails. text_matches/images_match are injected so this orchestration stays
free of PDF/image-library specifics - see content_match.py and
image_similarity.py for the real implementations.

A container node's own `content` is never text-compared directly: the web
pipeline's `content` for a node with children includes its descendants'
text too (concatenated), while the PDF pipeline's holds only that node's
own immediate text - comparing them would spuriously fail almost every
container. Only a true leaf (no children on the PDF side) gets a real text
comparison; a container's own text is trivially ok once matched, and
rollup from its children (and any images it owns) covers the rest.

Table rows/cells are the one exception to the unified_number join: rows are
numbered by position, so a row present on only one side would shift every
row below it. table_counterparts_in pairs them by content instead (see
row_alignment.py), and compare_trees looks each one up through that map."""

import re
from collections.abc import Callable

from comparison.row_alignment import table_counterparts, table_pairs

# (pdf node, web node) -> whether they show the same content.
TextMatcher = Callable[[dict, dict], bool]
ImageMatcher = Callable[[dict, dict], bool]


def _index_nodes(node: dict, into: dict[str, dict]) -> None:
    if node.get("unified_number"):
        into[node["unified_number"]] = node
    for child in node.get("children", []):
        _index_nodes(child, into)


def _index_images(images: list[dict]) -> dict[str, dict]:
    return {img["unified_number"]: img for img in images if img.get("unified_number")}


def _images_by_owner(images: list[dict]) -> dict[str, list[dict]]:
    by_owner: dict[str, list[dict]] = {}
    for img in images:
        if not img.get("unified_number"):
            continue
        by_owner.setdefault(img.get("owner_citation", ""), []).append(img)
    return by_owner


def _tables(node: dict):
    if node.get("type") == "Table" and node.get("unified_number"):
        yield node
    for child in node.get("children", []):
        yield from _tables(child)


_TABLE_ORDINAL = re.compile(r"\.Tbl(\d+)$")


def _ordinal(table: dict) -> int:
    match = _TABLE_ORDINAL.search(table["unified_number"])
    return int(match.group(1)) if match else 0


def _tables_by_scope(tree: dict) -> dict[str, list[dict]]:
    """Tables grouped by the article/note their "...TblN" number counts in,
    in N order - not tree order, which differs where a table sits deeper
    than its siblings (the PDF numbers them in page order)."""
    scopes: dict[str, list[dict]] = {}
    for table in _tables(tree):
        scopes.setdefault(_TABLE_ORDINAL.sub("", table["unified_number"]), []).append(table)
    return {scope: sorted(tables, key=_ordinal) for scope, tables in scopes.items()}


def _unpaired(node: dict) -> dict[str, None]:
    unpaired = {node["unified_number"]: None}
    for child in node.get("children", []):
        unpaired.update(_unpaired(child))
    return unpaired


def _scope_counterparts(
    pdf_tables: list[dict], web_tables: list[dict], web_nodes: dict
) -> dict[str, str | None]:
    pairs = table_pairs(pdf_tables, web_tables)
    counterparts: dict[str, str | None] = {}
    for index, pdf_table in enumerate(pdf_tables):
        if index in pairs:
            web_table = web_tables[pairs[index]]
            counterparts[pdf_table["unified_number"]] = web_table["unified_number"]
            counterparts.update(table_counterparts(pdf_table, web_table))
        elif pdf_table["unified_number"] in web_nodes:
            # Unpaired, yet a web table has its number: never compare the two.
            counterparts.update(_unpaired(pdf_table))
    return counterparts


def table_counterparts_in(pdf_tree: dict, web_tree: dict | None) -> dict[str, str | None]:
    """Table/row/cell counterparts: each article's tables pair by title
    (table_pairs), then each paired table's rows and cells by content."""
    web_nodes: dict[str, dict] = {}
    web_scopes: dict[str, list[dict]] = {}
    if web_tree is not None:
        _index_nodes(web_tree, web_nodes)
        web_scopes = _tables_by_scope(web_tree)
    counterparts: dict[str, str | None] = {}
    for scope, pdf_tables in _tables_by_scope(pdf_tree).items():
        web_tables = web_scopes.get(scope, [])
        counterparts.update(_scope_counterparts(pdf_tables, web_tables, web_nodes))
    return counterparts


def _web_node_for(unified_number: str, web_nodes: dict, counterparts: dict) -> dict | None:
    if not unified_number:
        return None
    web_number = counterparts.get(unified_number, unified_number)
    return web_nodes.get(web_number) if web_number else None


def compare_trees(
    pdf_tree: dict,
    pdf_images: list[dict],
    web_tree: dict | None,
    web_images: list[dict],
    text_matches: TextMatcher,
    images_match: ImageMatcher,
    counterparts: dict[str, str | None] | None = None,
) -> dict[str, bool]:
    web_nodes: dict[str, dict] = {}
    if web_tree is not None:
        _index_nodes(web_tree, web_nodes)
    counterparts = counterparts or {}
    web_image_index = _index_images(web_images)
    pdf_images_by_owner = _images_by_owner(pdf_images)
    statuses: dict[str, bool] = {}

    def image_status(pdf_image: dict) -> bool:
        unified_number = pdf_image["unified_number"]
        web_image = web_image_index.get(unified_number)
        status = web_image is not None and images_match(pdf_image, web_image)
        statuses[unified_number] = status
        return status

    def own_text_ok(pdf_node: dict, web_node: dict | None, unified_number: str) -> bool:
        if web_node is None:
            return not unified_number
        if pdf_node.get("children"):
            return True
        return text_matches(pdf_node, web_node)

    def node_status(pdf_node: dict) -> bool:
        unified_number = pdf_node.get("unified_number", "")
        web_node = _web_node_for(unified_number, web_nodes, counterparts)
        own_ok = own_text_ok(pdf_node, web_node, unified_number)
        # Eagerly evaluated as lists, not passed straight to all(...) as
        # generators - all() short-circuits on the first False, which would
        # skip visiting (and recording a status for) every sibling/image
        # after the first failure instead of just skipping the AND check.
        owned_image_statuses = [
            image_status(img) for img in pdf_images_by_owner.get(pdf_node.get("citation", ""), [])
        ]
        child_statuses = [node_status(child) for child in pdf_node.get("children", [])]
        owned_images_ok = all(owned_image_statuses)
        children_ok = all(child_statuses)
        result = own_ok and owned_images_ok and children_ok
        if unified_number:
            statuses[unified_number] = result
        return result

    node_status(pdf_tree)
    return statuses
