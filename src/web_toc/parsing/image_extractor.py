"""Walks one section/appendix/spectables/front-matter-article content JSON
for {"type": "figure", ...} nodes, wherever they're nested (directly in an
article's content, or inside a table cell), and assigns each one an owner by
stripping trailing dot-segments off its own id until the remainder matches a
real node's citation. Every figure's id already encodes its full ancestor
chain, so - unlike the PDF pipeline's image_matcher.py - no position/bbox
comparison is needed here at all.
"""

from web_toc.domain.models import WebImage


def _resolve_owner(figure_id: str, citations: set[str], fallback_citation: str) -> str:
    parts = figure_id.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in citations:
            return candidate
        parts.pop()
    return fallback_citation


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
        graphic = figure.get("graphic", {})
        owner = _resolve_owner(figure["id"], citations, fallback_citation)
        images.append(
            WebImage(
                id=figure["id"],
                src=graphic.get("src", ""),
                alt_text=graphic.get("alt_text", ""),
                owner_citation=owner,
            )
        )
    return images
