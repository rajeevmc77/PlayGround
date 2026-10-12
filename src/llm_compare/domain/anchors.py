"""Which element of a saved web page an image's id points at, when the page does not carry
the id itself: the saved pages id their tables, rows and articles with the same dotted path
the image ids extend, so stripping trailing segments finds the nearest enclosing element."""

from collections.abc import Collection


def nearest_anchor(element_id: str, page_ids: Collection[str]) -> tuple[str, bool] | None:
    """(anchor, exact): the id itself when the page has it, else its longest dotted prefix
    the page has (exact False), else None."""
    if element_id and element_id in page_ids:
        return element_id, True
    candidate = element_id
    while "." in candidate:
        candidate = candidate.rsplit(".", 1)[0]
        if candidate and candidate in page_ids:
            return candidate, False
    return None
