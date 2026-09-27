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

from collections.abc import Callable

from comparison.row_alignment import table_counterparts

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


def table_counterparts_in(pdf_tree: dict, web_tree: dict | None) -> dict[str, str | None]:
    """Row/cell counterparts for every table present on both sides."""
    web_nodes: dict[str, dict] = {}
    if web_tree is not None:
        _index_nodes(web_tree, web_nodes)
    counterparts: dict[str, str | None] = {}
    for pdf_table in _tables(pdf_tree):
        web_table = web_nodes.get(pdf_table["unified_number"])
        if web_table is not None:
            counterparts.update(table_counterparts(pdf_table, web_table))
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
