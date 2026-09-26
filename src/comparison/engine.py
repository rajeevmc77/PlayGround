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
rollup from its children (and any images it owns) covers the rest."""

from collections.abc import Callable

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


def compare_trees(
    pdf_tree: dict,
    pdf_images: list[dict],
    web_tree: dict | None,
    web_images: list[dict],
    text_matches: TextMatcher,
    images_match: ImageMatcher,
) -> dict[str, bool]:
    web_nodes: dict[str, dict] = {}
    if web_tree is not None:
        _index_nodes(web_tree, web_nodes)
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
        web_node = web_nodes.get(unified_number) if unified_number else None
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
