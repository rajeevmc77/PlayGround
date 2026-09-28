"""Walks one section/appendix/spectables/front-matter-article content JSON
for {"type": "figure", ...} nodes, wherever they're nested (directly in an
article's content, or inside a table cell), and assigns each one an owner by
stripping trailing dot-segments off its own id until the remainder matches a
real node's citation. Every figure's id already encodes its full ancestor
chain, so - unlike the PDF pipeline's image_matcher.py - no position/bbox
comparison is needed here at all.
"""

from web_toc.domain.models import WebImage
from web_toc.parsing.owner_resolution import resolve_owner


def _children(node) -> list:
    if isinstance(node, dict):
        return list(node.values())
    return node if isinstance(node, list) else []


def _walk_figures(node, holder_id: str | None = None):
    """Every figure in document order, with the id of the nearest node
    around it that has one."""
    is_dict = isinstance(node, dict)
    if is_dict and node.get("type") == "figure":
        yield node, holder_id
    inner_id = (node.get("id") if is_dict else None) or holder_id
    for child in _children(node):
        yield from _walk_figures(child, inner_id)


def _figure_ids(content: dict):
    """(figure, its id). A figure without an id of its own - Spec Table 1's
    wall-assembly drawings, some Appendix D and Part 9 note figures, each in
    a table row - is named after the node holding it: "<row id>.figureN".
    One with no id around it either is left out."""
    unnamed: dict[str, int] = {}
    for figure, holder_id in _walk_figures(content):
        if figure.get("id"):
            yield figure, figure["id"]
        elif holder_id:
            unnamed[holder_id] = unnamed.get(holder_id, 0) + 1
            yield figure, f"{holder_id}.figure{unnamed[holder_id]}"


def extract_images(content: dict, citations: set[str], fallback_citation: str) -> list[WebImage]:
    images = []
    for figure, figure_id in _figure_ids(content):
        graphic = figure.get("graphic", {})
        owner = resolve_owner(figure_id, citations, fallback_citation)
        images.append(
            WebImage(
                id=figure_id,
                src=graphic.get("src", ""),
                alt_text=graphic.get("alt_text", ""),
                owner_citation=owner,
            )
        )
    return images
