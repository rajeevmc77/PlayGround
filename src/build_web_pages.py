#!/usr/bin/env python3
"""Snapshots the live BC Building Code website to the local machine - the only
step that talks to the site; build_web_toc.py then builds offline from it:

- output/web_source/: the navigation tree and every content JSON.
- output/web_pages/: each rendered reading page (`main.ui-ContentPanel`),
  scrolled until every table row the content JSON lists has lazy-loaded, plus
  a local mirror of every stylesheet, font and image the pages use.
- output/web_pages/<citation>.layout.json: every element's xpath, rendered
  text and bbox, measured on the saved local copy (see layout_script.py).
- output/web_images/: every figure's image file.

Pages are rendered in a real headless browser - the site is client-rendered,
so a plain HTTP fetch only returns an empty shell - with many tabs in flight
at once rather than one page after another. Exits non-zero if any table
could not be fully loaded.

Usage:
    python3 src/build_web_pages.py
    python3 src/build_web_pages.py --version 2024 --date 2024-03-08
    python3 src/build_web_pages.py --only nbc.divBV2.part9.sect38
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web_toc.domain.models import ScrapedPage, WebNode
from web_toc.output.image_downloader import download_images
from web_toc.output.page_writer import AssetSource, citation_file, download_assets, write_page
from web_toc.output.source_cache import cache_contents, write_navigation, write_snapshot
from web_toc.parsing.image_extractor import extract_images
from web_toc.parsing.local_page_server import serve_pages
from web_toc.parsing.page_html import clean_panel, compose_page, image_paths
from web_toc.parsing.page_source import PageSource, PlaywrightPageSource
from web_toc.parsing.page_targets import page_targets, page_url
from web_toc.parsing.revisions import resolve_revisions
from web_toc.parsing.site_css import build_nav_css, css_url_paths, rebase_css_urls
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.table_extractor import table_row_counts
from web_toc.parsing.tree_builder import build_tree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://dev.buildingcode.gov.bc.ca"
DEFAULT_VERSION = "2024"
DEFAULT_DATE = "2024-03-08"
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")

# Each in-flight page is a whole browser tab running the site's own JS, so
# this stays lower than the plain-HTTP fetch concurrency elsewhere.
PAGE_FETCH_CONCURRENCY = 6
NAV_CSS_PATTERN = "nav-tree|breadcrumbs"
LAYOUT_SUFFIX = ".layout.json"


async def _scrape_one(
    browser: PageSource, semaphore: asyncio.Semaphore, url: str, expected: dict[str, int]
) -> ScrapedPage | None:
    """One retry in a fresh tab when a table stopped short of its rows."""
    async with semaphore:
        print(f"Rendering {url} ...", file=sys.stderr)
        page = await browser.fetch_page(url, expected)
        if page is None or not page.incomplete:
            return page
        print(f"  retrying {url} (short tables: {page.incomplete})", file=sys.stderr)
        return await browser.fetch_page(url, expected) or page


async def scrape_pages(
    browser: PageSource, urls: list[str], expected: list[dict[str, int]]
) -> list[ScrapedPage | None]:
    semaphore = asyncio.Semaphore(PAGE_FETCH_CONCURRENCY)
    return await asyncio.gather(
        *(_scrape_one(browser, semaphore, url, rows) for url, rows in zip(urls, expected, strict=True))
    )


def _save_page(pages_dir: Path, citation: str, scraped: ScrapedPage) -> set[str]:
    """Writes one composed page; returns the site asset paths it needs."""
    panel, icon_symbol = clean_panel(scraped.panel)
    inline_styles = [rebase_css_urls(css, "/") for css in scraped.inline_styles]
    html = compose_page(panel, scraped.stylesheets, inline_styles, icon_symbol, scraped.title)
    write_page(pages_dir, citation, html)
    inline_assets = {path for css in scraped.inline_styles for path in css_url_paths(css, "/")}
    return {*scraped.stylesheets, *image_paths(scraped.panel), *inline_assets}


def save_pages(
    pages_dir: Path, targets: list[WebNode], scraped: list[ScrapedPage | None]
) -> tuple[dict[str, str], set[str]]:
    manifest: dict[str, str] = {}
    assets: set[str] = set()
    for node, page in zip(targets, scraped, strict=True):
        if page is None:
            print(f"  skipped {node.citation} (no reading page rendered)", file=sys.stderr)
            continue
        assets |= _save_page(pages_dir, node.citation, page)
        manifest[node.citation] = page.title
    return manifest, assets


def incomplete_pages(
    targets: list[WebNode], scraped: list[ScrapedPage | None]
) -> dict[str, dict[str, list[int]]]:
    return {
        node.citation: page.incomplete
        for node, page in zip(targets, scraped, strict=True)
        if page is not None and page.incomplete
    }


def _stylesheet_asset_paths(assets_dir: Path, stylesheets: list[str]) -> list[str]:
    paths: list[str] = []
    for href in stylesheets:
        local = assets_dir / href.lstrip("/")
        if local.exists():
            paths.extend(css_url_paths(local.read_text(encoding="utf-8"), href))
    return list(dict.fromkeys(paths))


async def mirror_assets(assets: set[str], http: AssetSource, assets_dir: Path) -> None:
    """Pages' own assets first, then whatever the downloaded stylesheets
    themselves reference (fonts), which is only known once they're local."""
    failed = await download_assets(sorted(assets), http, assets_dir)
    stylesheets = sorted(path for path in assets if path.endswith(".css"))
    nested = _stylesheet_asset_paths(assets_dir, stylesheets)
    failed += await download_assets(nested, http, assets_dir)
    for path in failed:
        print(f"  skipped asset {path} (fetch failed)", file=sys.stderr)


async def _render_all(
    urls: list[str], expected: list[dict[str, int]]
) -> tuple[list[ScrapedPage | None], list[dict]]:
    async with PlaywrightPageSource() as browser:
        scraped = await scrape_pages(browser, urls, expected)
        nav_rules = await browser.fetch_nav_css(urls[0], NAV_CSS_PATTERN) if urls else []
    return scraped, nav_rules


async def _measure_one(
    browser: PageSource, semaphore: asyncio.Semaphore, base_url: str, citation: str
) -> tuple[str, dict | None]:
    async with semaphore:
        return citation, await browser.fetch_layout(f"{base_url}/{citation}.html")


async def measure_layouts(pages_dir: Path, citations: list[str]) -> None:
    """Measures each saved page as the viewer will render it - served
    locally, with the local asset mirror - and writes <citation>.layout.json."""
    semaphore = asyncio.Semaphore(PAGE_FETCH_CONCURRENCY)
    with serve_pages(pages_dir) as base_url:
        async with PlaywrightPageSource() as browser:
            results = await asyncio.gather(
                *(_measure_one(browser, semaphore, base_url, c) for c in citations)
            )
    for citation, layout in results:
        if layout is None:
            print(f"  no layout for {citation} (no content panel)", file=sys.stderr)
            continue
        target = citation_file(pages_dir, citation, LAYOUT_SUFFIX)
        target.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")


async def _download_figures(contents: dict[str, dict], http, images_dir: Path) -> None:
    images = [
        image
        for citation, content in contents.items()
        for image in extract_images(content, set(), citation)
    ]
    await download_images(images, http, str(images_dir))


def _selected_targets(root: WebNode, only: str | None) -> list[WebNode]:
    targets = page_targets(root)
    return [node for node in targets if node.citation == only] if only else targets


def _write_manifest(pages_dir: Path, manifest: dict[str, str], merge: bool) -> None:
    path = pages_dir / "pages.json"
    if merge and path.exists():
        manifest = {**json.loads(path.read_text(encoding="utf-8")), **manifest}
    pages_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")


async def _scrape_site(
    http, base_url: str, version: str, date: str, out: Path, only: str | None
) -> tuple[dict[str, str], list[dict], dict[str, dict[str, list[int]]]]:
    nav = await http.fetch_navigation_tree()
    write_navigation(out / "web_source", nav)
    write_snapshot(out / "web_source", version, date)
    root = build_tree(nav)
    served = await cache_contents(http, root, version, out / "web_source")
    # As of the date the pages are rendered for, so the rows expected match.
    contents = {c: resolve_revisions(content, date) or {} for c, content in served.items()}
    targets = _selected_targets(root, only)
    urls = [page_url(base_url, node, version, date) for node in targets]
    expected = [table_row_counts(contents.get(node.citation, {})) for node in targets]
    scraped, nav_rules = await _render_all(urls, expected)
    manifest, assets = save_pages(out / "web_pages", targets, scraped)
    await mirror_assets(assets, http, out / "web_pages" / "assets")
    await _download_figures(contents, http, out / "web_images")
    return manifest, nav_rules, incomplete_pages(targets, scraped)


async def run(
    base_url: str, version: str, date: str, output_dir: str, only: str | None = None
) -> dict[str, dict[str, list[int]]]:
    """Returns {page citation: {table id: [rendered, expected rows]}} for
    every page saved with a table the site never finished loading."""
    out = Path(output_dir)
    pages_dir = out / "web_pages"
    async with HttpxWebSource(base_url, version) as http:
        manifest, nav_rules, incomplete = await _scrape_site(
            http, base_url, version, date, out, only
        )
    assets_dir = pages_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "site-nav.css").write_text(build_nav_css(nav_rules), encoding="utf-8")
    _write_manifest(pages_dir, manifest, merge=only is not None)
    await measure_layouts(pages_dir, list(manifest))
    return incomplete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--date", default=DEFAULT_DATE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only", help="scrape just this page citation (kept pages stay)")
    args = parser.parse_args()
    incomplete = asyncio.run(run(args.base_url, args.version, args.date, args.output_dir, args.only))
    print(f"Wrote {args.output_dir}/web_pages/ and {args.output_dir}/web_source/", file=sys.stderr)
    for citation, tables in incomplete.items():
        print(f"INCOMPLETE {citation}: {tables} (rendered, expected rows)", file=sys.stderr)
    if incomplete:
        sys.exit(1)


if __name__ == "__main__":
    main()
