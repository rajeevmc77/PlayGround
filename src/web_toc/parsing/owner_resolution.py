"""Strip-and-match owner resolution shared by image_extractor.py and
table_extractor.py: a figure or table's own id already encodes its full
ancestor chain, so ownership is a pure string operation - strip trailing
dot-segments off the id until the remainder matches a real node's citation.
"""


def resolve_owner(item_id: str, citations: set[str], fallback_citation: str) -> str:
    parts = item_id.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in citations:
            return candidate
        parts.pop()
    return fallback_citation
