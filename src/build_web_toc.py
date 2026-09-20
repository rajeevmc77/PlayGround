#!/usr/bin/env python3
"""Parses the live BC Building Code website's navigation tree + per-section
content into output/web_toc.json: a hierarchical index plus every embedded
figure, matched to the deepest document node it belongs to.

Usage:
    python3 src/build_web_toc.py
    python3 src/build_web_toc.py --base-url https://dev.buildingcode.gov.bc.ca --version 2024
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web_toc.output.json_writer import write_json
from web_toc.parsing.content_url import content_url
from web_toc.parsing.image_extractor import extract_images
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.tree_builder import build_tree, collect_citations

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://dev.buildingcode.gov.bc.ca"
DEFAULT_VERSION = "2024"
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def run(base_url: str, version: str, output_dir: str) -> None:
    source = HttpxWebSource(base_url, version)
    root = build_tree(source.fetch_navigation_tree())
    citations = collect_citations(root)

    images = []
    for node in _walk(root):
        url = content_url(node, version)
        if url is None:
            continue
        print(f"Fetching {url} ...", file=sys.stderr)
        content = source.fetch_content(url)
        if content is None:
            print(f"  skipped (no content at {url})", file=sys.stderr)
            continue
        images.extend(extract_images(content, citations, node.citation))

    write_json(root, images, str(Path(output_dir) / "web_toc.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(f"Parsing {args.base_url} (version {args.version}) ...", file=sys.stderr)
    run(args.base_url, args.version, args.output_dir)
    print(f"Wrote {args.output_dir}/web_toc.json", file=sys.stderr)


if __name__ == "__main__":
    main()
