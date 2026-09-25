"""Caches the site's navigation tree and every content JSON under
output/web_source/, so build_web_toc.py can build without the network.

Content files are keyed by the citation of the node that fetches them (the
same content-bearing nodes `content_url` picks), not by their site URL.
"""

import asyncio
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from web_toc.domain.models import WebNode
from web_toc.output.page_writer import citation_file
from web_toc.parsing.content_url import content_url
from web_toc.parsing.site_source import WebSource

NAVIGATION_FILE = "navigation.json"
CONTENT_DIR = "content"

# I/O-bound HTTP fetches, not CPU work - a bounded semaphore overlaps the
# per-request latency without hammering the site with unbounded concurrency.
CONTENT_FETCH_CONCURRENCY = 8


def content_file(source_dir: Path, citation: str) -> Path | None:
    return citation_file(Path(source_dir) / CONTENT_DIR, citation, ".json")


def write_navigation(source_dir: Path, nav: dict) -> None:
    Path(source_dir).mkdir(parents=True, exist_ok=True)
    (Path(source_dir) / NAVIGATION_FILE).write_text(json.dumps(nav), encoding="utf-8")


def _walk(node: WebNode) -> Iterator[WebNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


async def _fetch(http: WebSource, semaphore: asyncio.Semaphore, url: str) -> dict | None:
    async with semaphore:
        print(f"Fetching {url} ...", file=sys.stderr)
        return await http.fetch_content(url)


def _write_content(source_dir: Path, citation: str, content: dict) -> None:
    target = content_file(source_dir, citation)
    if target is None:
        raise ValueError(f"Unsafe citation for a file name: {citation!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")


async def cache_contents(
    http: WebSource, root: WebNode, version: str, source_dir: Path
) -> dict[str, dict]:
    """Fetches and writes every content-bearing node's JSON; returns
    {citation: content} for the ones the site actually served."""
    targets = [(node, url) for node in _walk(root) if (url := content_url(node, version))]
    semaphore = asyncio.Semaphore(CONTENT_FETCH_CONCURRENCY)
    contents = await asyncio.gather(*(_fetch(http, semaphore, url) for _, url in targets))
    cached: dict[str, dict] = {}
    for (node, url), content in zip(targets, contents, strict=True):
        if content is None:
            print(f"  skipped (no content at {url})", file=sys.stderr)
            continue
        _write_content(source_dir, node.citation, content)
        cached[node.citation] = content
    return cached
