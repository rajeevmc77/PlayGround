import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import MagicMock, patch

import pytest

from build_mo_toc import drop_images_over_tables, main, run
from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.image_extractor import RawImage
from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)
from mo_toc.parsing.table_extractor import TableAnchor, TableRegion


def test_run_writes_mo_pdf_json_not_mo_toc_json(tmp_path):
    fake_lines = [[]]
    with (
        patch("build_mo_toc.extract_all_pages", return_value=(fake_lines, [], [[]], [[]])),
        patch("build_mo_toc.write_images", return_value=[]),
    ):
        run(pdf_path="unused.pdf", output_dir=str(tmp_path))

    assert (tmp_path / "mo_pdf.json").exists()
    assert not (tmp_path / "mo_toc.json").exists()
    payload = json.loads((tmp_path / "mo_pdf.json").read_text())
    assert payload["volume"]["type"] == "Volume"


@patch("build_mo_toc.write_json")
@patch("build_mo_toc.match_images")
@patch("build_mo_toc.write_images")
@patch("build_mo_toc.drop_images_over_tables")
@patch("build_mo_toc.assign_unified_numbers")
@patch("build_mo_toc.build_document")
@patch("build_mo_toc.extract_all_pages")
def test_run_wires_pipeline_in_order(
    mock_extract_all_pages,
    mock_build_document,
    mock_assign_numbers,
    mock_drop_images,
    mock_write_images,
    mock_match_images,
    mock_write_json,
    tmp_path,
):
    mock_extract_all_pages.return_value = (
        "ALL_LINES",
        "RAW_IMAGES",
        "TABLE_REGIONS",
        "DRAWING_RECTS",
    )
    mock_build_document.return_value = ("VOLUME", ["CAPTION"], "STITCHED_REGIONS")
    mock_drop_images.return_value = ["FILTERED_RAW_IMAGE"]
    mock_write_images.return_value = ["IMAGE_ASSET"]
    mock_match_images.return_value = ["MATCHED_IMAGE_ASSET"]

    manager = MagicMock()
    manager.attach_mock(mock_extract_all_pages, "extract_all_pages")
    manager.attach_mock(mock_build_document, "build_document")
    manager.attach_mock(mock_assign_numbers, "assign_unified_numbers")
    manager.attach_mock(mock_drop_images, "drop_images_over_tables")
    manager.attach_mock(mock_write_images, "write_images")
    manager.attach_mock(mock_match_images, "match_images")
    manager.attach_mock(mock_write_json, "write_json")

    run("some.pdf", str(tmp_path))

    mock_extract_all_pages.assert_called_once_with("some.pdf")
    mock_build_document.assert_called_once_with("ALL_LINES", "TABLE_REGIONS", "DRAWING_RECTS")
    mock_assign_numbers.assert_called_once_with(
        ["VOLUME"],
        MO_TOC_TYPE_MARKERS,
        identifier_types=MO_TOC_IDENTIFIER_TYPES,
        suffix_types=MO_TOC_SUFFIX_TYPES,
    )
    mock_drop_images.assert_called_once_with("RAW_IMAGES", "STITCHED_REGIONS")
    mock_write_images.assert_called_once_with(["FILTERED_RAW_IMAGE"], str(tmp_path / "images"))
    mock_match_images.assert_called_once_with(["IMAGE_ASSET"], ["CAPTION"], "VOLUME")
    mock_write_json.assert_called_once_with(
        "VOLUME", ["CAPTION"], ["MATCHED_IMAGE_ASSET"], str(tmp_path / "mo_pdf.json")
    )

    assert [c[0] for c in manager.mock_calls] == [
        "extract_all_pages",
        "build_document",
        "assign_unified_numbers",
        "drop_images_over_tables",
        "write_images",
        "match_images",
        "write_json",
    ]


def _raw_image(page, bbox):
    return RawImage(page=page, bbox=bbox, width=10, height=10, data=b"", ext="png", phash=None)


def _table_region_on_page(page_index, outer_bbox):
    # Represents both an anchored region and a continuation-synthesized one
    # (fill_continuation_gaps' output looks identical either way by the time
    # it reaches table_regions_by_page) - Finding 2 must drop images
    # overlapping either kind.
    table_node = Node(
        type="Table",
        identifier="X",
        citation="Table:X",
        title="",
        page=page_index + 1,
        end_page=page_index + 1,
        bbox=outer_bbox,
    )
    return TableRegion(
        anchor=TableAnchor(page_index=page_index, caption_line_idx=0, identifier="X"),
        table_node=table_node,
        forming_part_of=None,
        consumed_line_indices=set(),
        has_bottom_border=True,
        outer_bbox=outer_bbox,
    )


def test_drop_images_over_tables_drops_image_overlapping_a_continuation_table():
    # Confirmed real bug (Finding 2): a continuation page's own grid, seen
    # only via fill_continuation_gaps' synthesized TableRegion (no caption
    # of its own), still gets rendered and indexed as a spurious "figure"
    # image because raw_images was computed earlier, before continuation
    # regions existed, and never filtered against them.
    overlapping_image = _raw_image(page=527, bbox=(100.0, 100.0, 300.0, 300.0))
    unrelated_image = _raw_image(page=528, bbox=(50.0, 50.0, 90.0, 90.0))
    table_regions_by_page = [[] for _ in range(527)]
    table_regions_by_page[526] = [_table_region_on_page(526, BBox(90.0, 90.0, 310.0, 310.0))]

    kept = drop_images_over_tables([overlapping_image, unrelated_image], table_regions_by_page)

    assert kept == [unrelated_image]


def test_drop_images_over_tables_keeps_non_overlapping_image_on_a_table_page():
    non_overlapping_image = _raw_image(page=527, bbox=(1000.0, 1000.0, 1010.0, 1010.0))
    table_regions_by_page = [[] for _ in range(527)]
    table_regions_by_page[526] = [_table_region_on_page(526, BBox(90.0, 90.0, 310.0, 310.0))]

    kept = drop_images_over_tables([non_overlapping_image], table_regions_by_page)

    assert kept == [non_overlapping_image]


def test_main_exits_when_pdf_missing(tmp_path, monkeypatch):
    missing_pdf = str(tmp_path / "nope.pdf")
    monkeypatch.setattr(sys, "argv", ["build_mo_toc.py", missing_pdf])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert "No such file" in str(exc_info.value)
