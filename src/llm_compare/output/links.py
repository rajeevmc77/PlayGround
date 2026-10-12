"""Where each report row's images can be opened: the PDF at the image's page, and the saved
web page at the image's element - or at the nearest enclosing element that has an id."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote

from llm_compare.domain.anchors import nearest_anchor
from llm_compare.domain.models import PairRecord

ReadPage = Callable[[str], str | None]

_ID_ATTRIBUTE = re.compile(r"""\sid=(?:"([^"]*)"|'([^']*)')""")


@dataclass(frozen=True)
class RowLinks:
    pdf_href: str | None = None
    web_href: str | None = None
    web_anchor: str | None = None
    web_anchor_exact: bool | None = None


def page_ids(read_page: ReadPage, page_file: str) -> frozenset[str] | None:
    """Every `id` attribute of a saved page; None when the page is missing or unreadable."""
    try:
        html = read_page(page_file)
    except (OSError, UnicodeDecodeError):
        return None
    if html is None:
        return None
    return frozenset(unescape(double or single) for double, single in _ID_ATTRIBUTE.findall(html))


def _web_links(record: PairRecord, ids: frozenset[str] | None, asset_prefix: str) -> RowLinks:
    location = record.web_location
    if location is None or ids is None:
        return RowLinks()
    page = asset_prefix + quote(location.page_file)
    found = nearest_anchor(location.element_id, ids)
    if found is None:
        return RowLinks(web_href=page)
    anchor, exact = found
    return RowLinks(
        web_href=f"{page}#{quote(anchor, safe='')}", web_anchor=anchor, web_anchor_exact=exact
    )


def _pdf_href(record: PairRecord, base_href: str | None) -> str | None:
    if record.pdf_location is None or base_href is None:
        return None
    return f"{base_href}#page={record.pdf_location.page}"


def resolve_links(
    records: Iterable[PairRecord], *, read_page: ReadPage, pdf_href: str | None, asset_prefix: str
) -> dict[str, RowLinks]:
    """Links for every record. `pdf_href` is the PDF's own (already url-quoted, relative to the
    report) href, None when there is no PDF. Each distinct saved page is read once."""
    ids_by_page: dict[str, frozenset[str] | None] = {}
    links = {}
    for record in records:
        location = record.web_location
        if location is not None and location.page_file not in ids_by_page:
            ids_by_page[location.page_file] = page_ids(read_page, location.page_file)
        ids = ids_by_page.get(location.page_file) if location else None
        web = _web_links(record, ids, asset_prefix)
        links[record.row_id] = RowLinks(
            _pdf_href(record, pdf_href), web.web_href, web.web_anchor, web.web_anchor_exact
        )
    return links
