"""Derives each content-bearing node's own content-JSON URL directly from its
id/path - no ancestor traversal needed, since the site's own ids already
encode the full division/part/section chain (verified against the live site;
see ai_docs/2026-09-20-web-toc-images-design.md). `index`/`conversions` nodes
and regular (non-front-matter) articles return None: no working URL was found
for the former, and the latter's figures are already covered by their parent
section's own content fetch.
"""
import re

from web_toc.domain.models import WebNode

_SECTION_RE = re.compile(r"^(?P<div>.+)\.part(?P<part>\d+)\.sect(?P<sect>\d+)$")
_PART_APPENDIX_RE = re.compile(r"^(?P<div>.+)\.part(?P<part>\d+)\.appendix$")
_DIVISION_APPENDIX_RE = re.compile(r"^(?P<div>.+)\.appendix(?P<letter>[A-Za-z])$")
_SPECTABLES_RE = re.compile(r"^(?P<div>.+)\.part(?P<part>\d+)\.spectables(?P<num>\d+)$")


def _div_slug(div_id: str) -> str:
    return div_id.lower().replace(".", "-")


def content_url(node: WebNode, version: str) -> str | None:
    base = f"/data/{version}/content"
    if node.type == "section":
        m = _SECTION_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/part-{m['part']}/section-{m['sect']}.json" if m else None
    if node.type == "part_appendix":
        m = _PART_APPENDIX_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/part-{m['part']}/appendix.json" if m else None
    if node.type == "division_appendix":
        m = _DIVISION_APPENDIX_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/appendix-{m['letter'].lower()}.json" if m else None
    if node.type == "spectables":
        m = _SPECTABLES_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/part-{m['part']}/spectables/{m['num']}.json" if m else None
    if node.type == "article" and node.path.startswith("/code/front-matter/"):
        slug = node.path.rstrip("/").rsplit("/", 1)[-1]
        return f"{base}/front-matter/{slug}.json"
    return None
