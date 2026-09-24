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


def _walk_figures(node):
    if isinstance(node, dict):
        if node.get("type") == "figure":
            yield node
        for value in node.values():
            yield from _walk_figures(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_figures(item)


def extract_images(content: dict, citations: set[str], fallback_citation: str) -> list[WebImage]:
    images = []
    for figure in _walk_figures(content):
        figure_id = figure.get("id")
        if figure_id is None:
            continue
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
