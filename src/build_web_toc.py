#!/usr/bin/env python3
"""Builds output/bcbc_web.json offline from the local snapshot that
build_web_pages.py saved: a hierarchical index plus every embedded figure,
table, and Sentence/Clause/Subclause body-text node, each matched to the
deepest document node it belongs to, carrying the text the site renders and
a location - {page_file, xpath, bbox} - in the locally saved page.

Structure (ids, numbering, table grid) comes from the cached navigation tree
and content JSON under output/web_source/; text and locations come from
output/web_pages/<citation>.layout.json.

Usage:
    python3 src/build_web_pages.py   # once, needs the network
    python3 src/build_web_toc.py
"""

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared.numbering import assign_unified_numbers, number_images
from web_toc.domain.models import WebImage, WebNode
from web_toc.output.json_writer import write_json
from web_toc.output.page_writer import citation_file
from web_toc.parsing.body_extractor import attach_body, extract_body
from web_toc.parsing.image_extractor import extract_images
from web_toc.parsing.layout_join import join_layout, location_report
from web_toc.parsing.local_source import LocalWebSource
from web_toc.parsing.note_extractor import extract_notes
from web_toc.parsing.numbering_config import WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES
from web_toc.parsing.owner_resolution import attach_owned_nodes
from web_toc.parsing.page_targets import page_targets
from web_toc.parsing.revisions import resolve_revisions
from web_toc.parsing.table_extractor import attach_tables, extract_tables
from web_toc.parsing.tree_builder import build_tree, collect_citations

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")
IMAGES_DIR = "web_images"
LAYOUT_SUFFIX = ".layout.json"


def _walk(node: WebNode) -> Iterator[WebNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _cached_contents(
    root: WebNode, source: LocalWebSource, date: str
) -> list[tuple[WebNode, dict]]:
    """Every node build_web_pages.py cached content JSON for, read as of the
    date its pages were rendered for."""
    fetched = []
    for node in list(_walk(root)):
        served = source.fetch_content(node.citation)
        content = resolve_revisions(served, date) if served is not None else None
        if content is not None:
            fetched.append((node, content))
    return fetched


def _attach_notes(root, fetched, citations: set[str]) -> set[str]:
    """Notes go in first so an appnote's own tables/figures resolve to the
    Note rather than its part_appendix. Each Note is owned by the node whose
    content held it. Returns the widened citation set."""
    notes = [owned for node, content in fetched for owned in extract_notes(content, node.citation)]
    attach_owned_nodes(root, notes)
    return citations | {note.citation for _, note in notes}


def _extract_owned(fetched, citations: set[str]):
    images, owned_tables, owned_sentences = [], [], []
    for node, content in fetched:
        images.extend(extract_images(content, citations, node.citation))
        owned_tables.extend(extract_tables(content, citations, node.citation))
        owned_sentences.extend(extract_body(content, citations, node.citation))
    return images, owned_tables, owned_sentences


def _set_local_paths(images: list[WebImage], out: Path) -> None:
    for image in images:
        relative = f"{IMAGES_DIR}/{image.id}.jpg"
        if (out / relative).is_file():
            image.local_path = relative


def _load_layouts(pages_dir: Path, page_citations: list[str]) -> dict[str, dict]:
    layouts = {}
    for citation in page_citations:
        path = citation_file(pages_dir, citation, LAYOUT_SUFFIX)
        if path is None or not path.exists():
            print(f"  no layout for {citation} (page not scraped)", file=sys.stderr)
            continue
        layouts[citation] = json.loads(path.read_text(encoding="utf-8"))
    return layouts


def _print_report(report: dict[str, dict[str, int]]) -> None:
    print("Locations found:", file=sys.stderr)
    for type_, counts in sorted(report.items()):
        print(
            f"  {type_}: {counts['located']} located, {counts['unlocated']} unlocated",
            file=sys.stderr,
        )


def _build_tree(source: LocalWebSource) -> tuple[WebNode, list[WebImage]]:
    root = build_tree(source.fetch_navigation_tree())
    fetched = _cached_contents(root, source, source.fetch_snapshot()["date"])
    citations = _attach_notes(root, fetched, collect_citations(root))
    images, owned_tables, owned_sentences = _extract_owned(fetched, citations)
    attach_tables(root, owned_tables)
    attach_body(root, owned_sentences)
    # Runs after attach_tables/attach_body so the nodes they just added
    # get numbered too - matching the pdf pipeline's build_mo_toc.py,
    # which also numbers only after its own attach_tables call. Images
    # are numbered from the same scope map so a figure's key lines up
    # with its owning node's cross-source key.
    scope_by_citation = assign_unified_numbers(root.children, WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES)
    number_images(images, scope_by_citation)
    return root, images


def run(output_dir: str) -> None:
    out = Path(output_dir)
    root, images = _build_tree(LocalWebSource(out / "web_source"))
    _set_local_paths(images, out)
    pages = [node.citation for node in page_targets(root)]
    layouts = _load_layouts(out / "web_pages", pages)
    join_layout(root, images, layouts, set(pages))
    _print_report(location_report(root, images))
    write_json(root, images, str(out / "bcbc_web.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    run(args.output_dir)
    print(f"Wrote {args.output_dir}/bcbc_web.json", file=sys.stderr)


if __name__ == "__main__":
    main()
