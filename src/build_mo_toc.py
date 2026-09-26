#!/usr/bin/env python3
"""Parses MO Package BCBC MRK signed.pdf into output/bcbc_pdf.json
and every embedded raster and vector-drawn image under output/images/.

Usage:
    python3 src/build_mo_toc.py                # uses data/<default PDF>
    python3 src/build_mo_toc.py /path/to/other.pdf
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mo_toc.domain.image_classification import is_equation_shaped
from mo_toc.domain.models import ImageAsset
from mo_toc.output.image_writer import write_images
from mo_toc.output.json_writer import write_json
from mo_toc.parsing.image_extractor import RawImage
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.notes_nesting import nest_notes_under_parts
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from mo_toc.parsing.parallel_extraction import extract_all_pages
from mo_toc.parsing.table_extractor import (
    TableRegion,
    attach_tables,
    fill_continuation_gaps,
    stitch_continuations,
)
from mo_toc.parsing.tree_builder import build_tree_from_lines
from mo_toc.parsing.vector_cluster import exclude_overlapping_rects
from shared.numbering import assign_unified_numbers, number_images

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def _consumed_by_page(table_regions_by_page: list[list]) -> dict[int, set[int]]:
    return {
        page_index: {i for region in regions for i in region.consumed_line_indices}
        for page_index, regions in enumerate(table_regions_by_page)
        if regions
    }


def build_document(all_lines, table_regions_by_page, all_drawing_rects):
    """Builds the fully-tabled tree: gap-fills continuation-page table
    regions, builds the Volume tree around them, then stitches and attaches
    the resulting tables to their owning nodes. Shared by run() and by
    tests/test_integration_real_pdf.py, which needs the same real pipeline
    (not just build_tree_from_lines) to assert on attached tables.
    """
    table_regions_by_page = fill_continuation_gaps(
        all_lines, all_drawing_rects, table_regions_by_page
    )
    volume, captions = build_tree_from_lines(
        all_lines, len(all_lines), consumed_by_page=_consumed_by_page(table_regions_by_page)
    )
    nest_notes_under_parts(volume)
    attach_tables(volume, stitch_continuations(table_regions_by_page), captions)
    return volume, captions, table_regions_by_page


def _table_bboxes_by_page(
    table_regions_by_page: list[list[TableRegion]],
) -> dict[int, list[tuple[float, float, float, float]]]:
    return {
        page_index: [region.outer_bbox.as_tuple() for region in regions]
        for page_index, regions in enumerate(table_regions_by_page)
        if regions
    }


def _is_droppable(image: RawImage, table_bboxes_by_page: dict[int, list]) -> bool:
    if image.kind != "vector":
        return False
    table_bboxes = table_bboxes_by_page.get(image.page - 1, [])
    return not exclude_overlapping_rects([image.bbox], table_bboxes)


def drop_images_over_tables(
    raw_images: list[RawImage], table_regions_by_page: list[list[TableRegion]]
) -> list[RawImage]:
    """Drops a VECTOR-DERIVED raw image whose bbox overlaps a table region's
    outer bbox on the same page (anchored or continuation-synthesized
    alike). Never drops a raster image (kind="raster") on that basis alone -
    a genuine embedded image (an equation, a diagram, a photo) can
    legitimately sit inside/near a table's own bbox; only a vector-cluster
    crop of the table's own gridlines is ever a false-positive "figure".

    fill_continuation_gaps synthesizes additional table regions for
    continuation pages in a later, sequential pass - AFTER raw_images was
    already computed per-page inside extract_all_pages/_extract_page, which
    only ever excluded the anchored table_regions_by_page bboxes known at
    that time. Without this filter, a continuation page's own grid still
    gets rendered and indexed as a spurious vector "figure" image (confirmed
    on 527 real pages of the source document). An earlier version of this
    filter dropped ANY image regardless of kind, which turned out to also
    discard 154 genuine embedded raster images across 81 real pages -
    reviewer-confirmed regression, fixed by the kind == "vector" guard here.
    """
    table_bboxes_by_page = _table_bboxes_by_page(table_regions_by_page)
    return [image for image in raw_images if not _is_droppable(image, table_bboxes_by_page)]


def _is_decorative(image) -> bool:
    return image.decorative


def _overlaps_a_table(image: ImageAsset, table_bboxes_by_page: dict[int, list]) -> bool:
    table_bboxes = table_bboxes_by_page.get(image.page - 1, [])
    if not table_bboxes:
        return False
    return not exclude_overlapping_rects([image.bbox.as_tuple()], table_bboxes)


def _is_equation(image: ImageAsset, table_bboxes_by_page: dict[int, list]) -> bool:
    if image.decorative or image.caption_kind is not None:
        return False
    width, height = image.bbox.x1 - image.bbox.x0, image.bbox.y1 - image.bbox.y0
    if not is_equation_shaped(width, height):
        return False
    return not _overlaps_a_table(image, table_bboxes_by_page)


def partition_equations(
    images: list[ImageAsset], table_regions_by_page: list[list[TableRegion]]
) -> tuple[list[ImageAsset], list[ImageAsset]]:
    """Splits out the images that read as an inline formula - wide/short,
    uncaptioned (a real Figure caption always wins), and not embedded in a
    table's own cell (that's a repeated assembly diagram, not a formula) -
    from the rest, so the two groups can be keyed `EqN`/`FigN` separately
    the same way web_toc's MathJax-screenshot equations already are (see
    shared/numbering.py's number_images `label` param). Every image ends up
    in exactly one of the two returned lists.
    """
    table_bboxes_by_page = _table_bboxes_by_page(table_regions_by_page)
    equations, figures = [], []
    for image in images:
        target = equations if _is_equation(image, table_bboxes_by_page) else figures
        target.append(image)
    return equations, figures


def run(pdf_path: str, output_dir: str) -> None:
    all_lines, raw_images, table_regions_by_page, all_drawing_rects = extract_all_pages(pdf_path)
    volume, captions, table_regions_by_page = build_document(
        all_lines, table_regions_by_page, all_drawing_rects
    )
    scope_by_citation = assign_unified_numbers([volume], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)
    raw_images = drop_images_over_tables(raw_images, table_regions_by_page)
    images = write_images(raw_images, str(Path(output_dir) / "images"))
    images = match_images(images, captions, volume)
    equations, figures = partition_equations(images, table_regions_by_page)
    number_images(figures, scope_by_citation, skip=_is_decorative)
    number_images(equations, scope_by_citation, label="Eq")
    write_json(volume, captions, images, str(Path(output_dir) / "bcbc_pdf.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pdf_path", nargs="?", default=DEFAULT_PDF)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    if not Path(args.pdf_path).exists():
        sys.exit(f"No such file: {args.pdf_path}")
    print(f"Parsing {args.pdf_path} ...", file=sys.stderr)
    run(args.pdf_path, args.output_dir)
    print(f"Wrote {args.output_dir}/bcbc_pdf.json, images/", file=sys.stderr)


if __name__ == "__main__":
    main()
