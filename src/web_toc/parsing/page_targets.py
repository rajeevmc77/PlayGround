"""Picks which navigation nodes get their own scraped reading page.

Only nodes the live site renders as a standalone page are scraped. A
subsection's or regular article's page on the site is just its parent
section page cut down to the Part title plus that one block (confirmed by
comparing the live DOMs), so the viewer derives those from the section page
instead of scraping ~2500 near-duplicate pages. Volumes and divisions have
no reading page at all (/volume/N renders the homepage, /code/<division>
answers 403); the site's own tree only expands them.
"""

from collections.abc import Iterator

from web_toc.domain.models import WebNode

_PAGE_TYPES = {
    "part",
    "section",
    "part_appendix",
    "division_appendix",
    "spectables",
    "index",
    "conversions",
}
_FRONT_MATTER_PREFIX = "/code/front-matter/"


def _walk(node: WebNode) -> Iterator[WebNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _has_own_page(node: WebNode) -> bool:
    if not node.path:
        return False
    if node.type in _PAGE_TYPES:
        return True
    return node.type == "article" and node.path.startswith(_FRONT_MATTER_PREFIX)


def page_targets(root: WebNode) -> list[WebNode]:
    return [node for node in _walk(root) if _has_own_page(node)]


def page_url(base_url: str, node: WebNode, version: str, date: str) -> str:
    return f"{base_url.rstrip('/')}{node.path}?version={version}&date={date}"
