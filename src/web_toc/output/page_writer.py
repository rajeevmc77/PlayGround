"""Writes scraped reading pages, and mirrors the site assets they reference
(stylesheets, fonts, images) under the same paths the site serves them at -
so the stylesheets' own relative url()s keep resolving unchanged.
"""

import asyncio
import posixpath
import re
from pathlib import Path
from typing import Protocol

# I/O-bound HTTP fetches, not CPU work - a bounded semaphore overlaps the
# per-request latency without hammering the site with unbounded concurrency.
DOWNLOAD_CONCURRENCY = 8

_SAFE_CITATION_RE = re.compile(r"^[\w.\-]+$")


class AssetSource(Protocol):
    async def fetch_bytes(self, path: str) -> bytes | None: ...


def asset_file(assets_dir: Path, site_path: str) -> Path | None:
    """Local mirror location for a site-root path, or None if it would
    escape `assets_dir`."""
    # normpath alone would silently turn "/../x" into "/x", so any ".."
    # segment is refused outright rather than normalised away.
    if not site_path.startswith("/") or ".." in site_path.split("/"):
        return None
    relative = posixpath.normpath(site_path).lstrip("/")
    return assets_dir / relative if relative else None


def page_file(pages_dir: Path, citation: str) -> Path | None:
    if not _SAFE_CITATION_RE.match(citation) or ".." in citation:
        return None
    return pages_dir / f"{citation}.html"


def write_page(pages_dir: Path, citation: str, html: str) -> None:
    target = page_file(pages_dir, citation)
    if target is None:
        raise ValueError(f"Unsafe citation for a file name: {citation!r}")
    pages_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")


async def _download_one(
    path: str, source: AssetSource, semaphore: asyncio.Semaphore, assets_dir: Path
) -> bool:
    target = asset_file(assets_dir, path)
    if target is None:
        return False
    async with semaphore:
        content = await source.fetch_bytes(path)
    if content is None:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return True


async def download_assets(paths: list[str], source: AssetSource, assets_dir: Path) -> list[str]:
    """Downloads every path concurrently; returns the ones that failed."""
    semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    results = await asyncio.gather(
        *(_download_one(path, source, semaphore, assets_dir) for path in paths)
    )
    return [path for path, ok in zip(paths, results, strict=True) if not ok]
