#!/usr/bin/env python3
"""Parses MO Package BCBC MRK signed.pdf into output/mo_pdf.json
and every embedded raster and vector-drawn image under output/images/.

Usage:
    python3 src/build_mo_toc.py                # uses data/<default PDF>
    python3 src/build_mo_toc.py /path/to/other.pdf
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mo_toc.output.image_writer import write_images
from mo_toc.output.json_writer import write_json
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)
from mo_toc.parsing.parallel_extraction import extract_all_pages
from mo_toc.parsing.table_extractor import attach_tables, stitch_continuations
from mo_toc.parsing.tree_builder import build_tree_from_lines
from shared.numbering import assign_unified_numbers

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def _consumed_by_page(table_regions_by_page: list[list]) -> dict[int, set[int]]:
    return {
        page_index: {i for region in regions for i in region.consumed_line_indices}
        for page_index, regions in enumerate(table_regions_by_page)
        if regions
    }


def run(pdf_path: str, output_dir: str) -> None:
    all_lines, raw_images, table_regions_by_page = extract_all_pages(pdf_path)
    volume, captions = build_tree_from_lines(
        all_lines, len(all_lines), consumed_by_page=_consumed_by_page(table_regions_by_page)
    )
    attach_tables(volume, stitch_continuations(table_regions_by_page), captions)
    assign_unified_numbers(
        [volume],
        MO_TOC_TYPE_MARKERS,
        identifier_types=MO_TOC_IDENTIFIER_TYPES,
        suffix_types=MO_TOC_SUFFIX_TYPES,
    )
    images = write_images(raw_images, str(Path(output_dir) / "images"))
    images = match_images(images, captions, volume)
    write_json(volume, captions, images, str(Path(output_dir) / "mo_pdf.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pdf_path", nargs="?", default=DEFAULT_PDF)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    if not Path(args.pdf_path).exists():
        sys.exit(f"No such file: {args.pdf_path}")
    print(f"Parsing {args.pdf_path} ...", file=sys.stderr)
    run(args.pdf_path, args.output_dir)
    print(f"Wrote {args.output_dir}/mo_pdf.json, images/", file=sys.stderr)


if __name__ == "__main__":
    main()
