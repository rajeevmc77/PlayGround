#!/usr/bin/env python3
"""Parses the live BC Building Code website's navigation tree + per-section
content into output/bcbc_web.json: a hierarchical index plus every embedded
figure, table, and Sentence/Clause/Subclause body-text node, each matched to
the deepest document node it belongs to.

Usage:
    python3 src/build_web_toc.py
    python3 src/build_web_toc.py --base-url https://dev.buildingcode.gov.bc.ca --version 2024
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared.numbering import assign_unified_numbers
from web_toc.output.image_downloader import download_images
from web_toc.output.json_writer import write_json
from web_toc.parsing.body_extractor import attach_body, extract_body
from web_toc.parsing.content_url import content_url
from web_toc.parsing.image_extractor import extract_images
from web_toc.parsing.numbering_config import (
    WEB_TOC_IDENTIFIER_TYPES,
    WEB_TOC_SUFFIX_TYPES,
    WEB_TOC_TYPE_MARKERS,
)
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.table_extractor import attach_tables, extract_tables
from web_toc.parsing.tree_builder import build_tree, collect_citations

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://dev.buildingcode.gov.bc.ca"
DEFAULT_VERSION = "2024"
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")

# I/O-bound HTTP fetches, not CPU work - a bounded semaphore overlaps the
# per-request latency without hammering the site with unbounded concurrency.
CONTENT_FETCH_CONCURRENCY = 8


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _content_bearing_nodes(root, version):
    for node in _walk(root):
        url = content_url(node, version)
        if url is not None:
            yield node, url


async def _fetch_content(source, semaphore, url):
    async with semaphore:
        print(f"Fetching {url} ...", file=sys.stderr)
        return await source.fetch_content(url)


async def run(base_url: str, version: str, output_dir: str) -> None:
    async with HttpxWebSource(base_url, version) as source:
        root = build_tree(await source.fetch_navigation_tree())
        citations = collect_citations(root)

        targets = list(_content_bearing_nodes(root, version))
        semaphore = asyncio.Semaphore(CONTENT_FETCH_CONCURRENCY)
        contents = await asyncio.gather(
            *(_fetch_content(source, semaphore, url) for _, url in targets)
        )

        images = []
        owned_tables = []
        owned_sentences = []
        for (node, url), content in zip(targets, contents, strict=True):
            if content is None:
                print(f"  skipped (no content at {url})", file=sys.stderr)
                continue
            images.extend(extract_images(content, citations, node.citation))
            owned_tables.extend(extract_tables(content, citations, node.citation))
            owned_sentences.extend(extract_body(content, citations, node.citation))

        attach_tables(root, owned_tables)
        attach_body(root, owned_sentences)
        # Runs after attach_tables/attach_body so the nodes they just added
        # get numbered too - matching the pdf pipeline's build_mo_toc.py,
        # which also numbers only after its own attach_tables call.
        assign_unified_numbers(
            root.children,
            WEB_TOC_TYPE_MARKERS,
            identifier_types=WEB_TOC_IDENTIFIER_TYPES,
            suffix_types=WEB_TOC_SUFFIX_TYPES,
        )

        await download_images(images, source, str(Path(output_dir) / "web_images"))

    write_json(root, images, str(Path(output_dir) / "bcbc_web.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(f"Parsing {args.base_url} (version {args.version}) ...", file=sys.stderr)
    asyncio.run(run(args.base_url, args.version, args.output_dir))
    print(f"Wrote {args.output_dir}/bcbc_web.json", file=sys.stderr)


if __name__ == "__main__":
    main()
