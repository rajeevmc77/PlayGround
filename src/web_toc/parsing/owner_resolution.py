"""Strip-and-match owner resolution and tree attachment shared by
image_extractor.py, table_extractor.py, and body_extractor.py: a figure,
table, or sentence's own id already encodes its full ancestor chain, so
ownership is a pure string operation - strip trailing dot-segments off the
id until the remainder matches a real node's citation.
"""

from web_toc.domain.models import WebNode


def resolve_owner(item_id: str, citations: set[str], fallback_citation: str) -> str:
    parts = item_id.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in citations:
            return candidate
        parts.pop()
    return fallback_citation


def _citation_index(node: WebNode, index: dict[str, WebNode]) -> dict[str, WebNode]:
    index[node.citation] = node
    for child in node.children:
        _citation_index(child, index)
    return index


def attach_owned_nodes(root: WebNode, owned: list[tuple[str, WebNode]]) -> None:
    index = _citation_index(root, {})
    for owner_citation, node in owned:
        owner = index.get(owner_citation)
        if owner is not None:
            owner.children.append(node)
