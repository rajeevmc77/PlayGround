#!/usr/bin/env python3
"""Snapshots the live BC Building Code website's own rendered reading pages
(`main.ui-ContentPanel`) into output/web_pages/, together with a local mirror
of every stylesheet, font and image they use, so the viewer's
"Table of Contents - web" tab can show each section exactly as the site does.

Pages are rendered in a real headless browser - the site is client-rendered,
so a plain HTTP fetch only returns an empty shell - with many tabs in flight
at once rather than one page after another.

Usage:
    python3 src/build_web_pages.py
    python3 src/build_web_pages.py --version 2024 --date 2024-03-08
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web_toc.domain.models import ScrapedPage, WebNode
from web_toc.output.page_writer import AssetSource, download_assets, write_page
from web_toc.parsing.page_html import clean_panel, compose_page, image_paths
from web_toc.parsing.page_source import PageSource, PlaywrightPageSource
from web_toc.parsing.page_targets import page_targets, page_url
from web_toc.parsing.site_css import build_nav_css, css_url_paths, rebase_css_urls
from web_toc.parsing.site_source import HttpxWebSource
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


async def _scrape_one(
    browser: PageSource, semaphore: asyncio.Semaphore, url: str
) -> ScrapedPage | None:
    async with semaphore:
        print(f"Rendering {url} ...", file=sys.stderr)
        return await browser.fetch_page(url)


async def scrape_pages(browser: PageSource, urls: list[str]) -> list[ScrapedPage | None]:
    semaphore = asyncio.Semaphore(PAGE_FETCH_CONCURRENCY)
    return await asyncio.gather(*(_scrape_one(browser, semaphore, url) for url in urls))


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


async def _render_all(urls: list[str]) -> tuple[list[ScrapedPage | None], list[dict]]:
    async with PlaywrightPageSource() as browser:
        scraped = await scrape_pages(browser, urls)
        nav_rules = await browser.fetch_nav_css(urls[0], NAV_CSS_PATTERN) if urls else []
    return scraped, nav_rules


async def run(base_url: str, version: str, date: str, output_dir: str) -> None:
    pages_dir = Path(output_dir) / "web_pages"
    assets_dir = pages_dir / "assets"
    async with HttpxWebSource(base_url, version) as http:
        targets = page_targets(build_tree(await http.fetch_navigation_tree()))
        urls = [page_url(base_url, node, version, date) for node in targets]
        scraped, nav_rules = await _render_all(urls)
        manifest, assets = save_pages(pages_dir, targets, scraped)
        await mirror_assets(assets, http, assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "site-nav.css").write_text(build_nav_css(nav_rules), encoding="utf-8")
    (pages_dir / "pages.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--date", default=DEFAULT_DATE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.version, args.date, args.output_dir))
    print(f"Wrote {args.output_dir}/web_pages/", file=sys.stderr)


if __name__ == "__main__":
    main()
