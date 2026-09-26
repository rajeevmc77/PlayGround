import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import MagicMock, patch

import pytest

from build_mo_toc import build_document, drop_images_over_tables, main, partition_equations, run
from mo_toc.domain.models import BBox, ImageAsset, Node
from mo_toc.parsing.image_extractor import RawImage
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from mo_toc.parsing.table_extractor import TableAnchor, TableRegion


def test_run_writes_bcbc_pdf_json_not_mo_toc_json(tmp_path):
    fake_lines = [[]]
    with (
        patch("build_mo_toc.extract_all_pages", return_value=(fake_lines, [], [[]], [[]])),
        patch("build_mo_toc.write_images", return_value=[]),
    ):
        run(pdf_path="unused.pdf", output_dir=str(tmp_path))

    assert (tmp_path / "bcbc_pdf.json").exists()
    assert not (tmp_path / "mo_toc.json").exists()
    payload = json.loads((tmp_path / "bcbc_pdf.json").read_text())
    assert payload["volume"]["type"] == "Volume"


@patch("build_mo_toc.write_json")
@patch("build_mo_toc.number_images")
@patch("build_mo_toc.partition_equations")
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
    mock_partition_equations,
    mock_number_images,
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
    mock_assign_numbers.return_value = {"SCOPE": "MAP"}
    mock_drop_images.return_value = ["FILTERED_RAW_IMAGE"]
    mock_write_images.return_value = ["IMAGE_ASSET"]
    mock_match_images.return_value = ["MATCHED_IMAGE_ASSET"]
    mock_partition_equations.return_value = (["EQUATION_IMAGE"], ["FIGURE_IMAGE"])

    manager = MagicMock()
    manager.attach_mock(mock_extract_all_pages, "extract_all_pages")
    manager.attach_mock(mock_build_document, "build_document")
    manager.attach_mock(mock_assign_numbers, "assign_unified_numbers")
    manager.attach_mock(mock_drop_images, "drop_images_over_tables")
    manager.attach_mock(mock_write_images, "write_images")
    manager.attach_mock(mock_match_images, "match_images")
    manager.attach_mock(mock_partition_equations, "partition_equations")
    manager.attach_mock(mock_number_images, "number_images")
    manager.attach_mock(mock_write_json, "write_json")

    run("some.pdf", str(tmp_path))

    mock_extract_all_pages.assert_called_once_with("some.pdf")
    mock_build_document.assert_called_once_with("ALL_LINES", "TABLE_REGIONS", "DRAWING_RECTS")
    mock_assign_numbers.assert_called_once_with(["VOLUME"], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)
    mock_drop_images.assert_called_once_with("RAW_IMAGES", "STITCHED_REGIONS")
    mock_write_images.assert_called_once_with(["FILTERED_RAW_IMAGE"], str(tmp_path / "images"))
    mock_match_images.assert_called_once_with(["IMAGE_ASSET"], ["CAPTION"], "VOLUME")
    mock_partition_equations.assert_called_once_with(["MATCHED_IMAGE_ASSET"], "STITCHED_REGIONS")
    assert mock_number_images.call_count == 2
    figures_call, equations_call = mock_number_images.call_args_list
    assert figures_call.args[0] == ["FIGURE_IMAGE"]
    assert figures_call.args[1] == {"SCOPE": "MAP"}
    skip = figures_call.kwargs["skip"]
    assert skip(SimpleNamespace(decorative=True)) is True
    assert skip(SimpleNamespace(decorative=False)) is False
    assert equations_call.args[0] == ["EQUATION_IMAGE"]
    assert equations_call.args[1] == {"SCOPE": "MAP"}
    assert equations_call.kwargs == {"label": "Eq"}
    mock_write_json.assert_called_once_with(
        "VOLUME", ["CAPTION"], ["MATCHED_IMAGE_ASSET"], str(tmp_path / "bcbc_pdf.json")
    )

    assert [c[0] for c in manager.mock_calls] == [
        "extract_all_pages",
        "build_document",
        "assign_unified_numbers",
        "drop_images_over_tables",
        "write_images",
        "match_images",
        "partition_equations",
        "number_images",
        "number_images",
        "write_json",
    ]


@patch("build_mo_toc.attach_tables")
@patch("build_mo_toc.stitch_continuations")
@patch("build_mo_toc.nest_notes_under_parts")
@patch("build_mo_toc.build_tree_from_lines")
@patch("build_mo_toc.fill_continuation_gaps")
def test_build_document_wires_nesting_in_order(
    mock_fill_continuation_gaps,
    mock_build_tree_from_lines,
    mock_nest_notes_under_parts,
    mock_stitch_continuations,
    mock_attach_tables,
):
    mock_fill_continuation_gaps.return_value = []
    mock_build_tree_from_lines.return_value = ("VOLUME", [])
    mock_stitch_continuations.return_value = []

    manager = MagicMock()
    manager.attach_mock(mock_fill_continuation_gaps, "fill_continuation_gaps")
    manager.attach_mock(mock_build_tree_from_lines, "build_tree_from_lines")
    manager.attach_mock(mock_nest_notes_under_parts, "nest_notes_under_parts")
    manager.attach_mock(mock_stitch_continuations, "stitch_continuations")
    manager.attach_mock(mock_attach_tables, "attach_tables")

    build_document([], [], [])

    assert [c[0] for c in manager.mock_calls] == [
        "fill_continuation_gaps",
        "build_tree_from_lines",
        "nest_notes_under_parts",
        "stitch_continuations",
        "attach_tables",
    ]


def _raw_image(page, bbox, kind="vector"):
    return RawImage(
        page=page, bbox=bbox, width=10, height=10, data=b"", ext="png", phash=None, kind=kind
    )


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


def test_drop_images_over_tables_keeps_a_raster_image_but_drops_a_vector_one():
    # Reviewer-confirmed regression: the original fix dropped ANY image
    # (raster or vector) overlapping a table bbox, but a genuine embedded
    # raster image (an equation, a diagram, a photo) can legitimately sit
    # inside/near a table's own bbox - only a vector-cluster-derived crop is
    # ever a table-gridline artifact worth dropping. Measured on the real
    # document: the over-broad filter silently discarded 154 genuine raster
    # images across 81 pages (e.g. page 502, 897, 1260).
    table_bbox = BBox(90.0, 90.0, 310.0, 310.0)
    raster_image = _raw_image(page=527, bbox=(100.0, 100.0, 300.0, 300.0), kind="raster")
    vector_image = _raw_image(page=527, bbox=(100.0, 100.0, 300.0, 300.0), kind="vector")
    table_regions_by_page = [[] for _ in range(527)]
    table_regions_by_page[526] = [_table_region_on_page(526, table_bbox)]

    kept = drop_images_over_tables([raster_image, vector_image], table_regions_by_page)

    assert kept == [raster_image]


def test_drop_images_over_tables_keeps_non_overlapping_image_on_a_table_page():
    non_overlapping_image = _raw_image(page=527, bbox=(1000.0, 1000.0, 1010.0, 1010.0))
    table_regions_by_page = [[] for _ in range(527)]
    table_regions_by_page[526] = [_table_region_on_page(526, BBox(90.0, 90.0, 310.0, 310.0))]

    kept = drop_images_over_tables([non_overlapping_image], table_regions_by_page)

    assert kept == [non_overlapping_image]


def _image_asset(page, bbox, caption_kind=None, decorative=False):
    return ImageAsset(
        page=page,
        bbox=bbox,
        width=10,
        height=10,
        phash=None,
        image_path="images/x.png",
        caption_kind=caption_kind,
        decorative=decorative,
    )


def test_partition_equations_puts_wide_uncaptioned_image_in_equations():
    formula = _image_asset(page=490, bbox=BBox(100.0, 100.0, 240.0, 126.0))

    equations, figures = partition_equations([formula], table_regions_by_page=[])

    assert equations == [formula]
    assert figures == []


def test_partition_equations_keeps_captioned_wide_image_as_a_figure():
    # A real Figure caption means it's a genuine figure, never relabeled as
    # an equation regardless of its shape.
    captioned = _image_asset(page=490, bbox=BBox(100.0, 100.0, 240.0, 126.0), caption_kind="Figure")

    equations, figures = partition_equations([captioned], table_regions_by_page=[])

    assert equations == []
    assert figures == [captioned]


def test_partition_equations_keeps_decorative_wide_image_as_a_figure():
    decorative = _image_asset(page=490, bbox=BBox(100.0, 100.0, 240.0, 126.0), decorative=True)

    equations, figures = partition_equations([decorative], table_regions_by_page=[])

    assert equations == []
    assert figures == [decorative]


def test_partition_equations_keeps_square_uncaptioned_image_as_a_figure():
    # A repeated icon/diagram, not a formula - equations always read wide.
    square = _image_asset(page=490, bbox=BBox(100.0, 100.0, 173.0, 173.0))

    equations, figures = partition_equations([square], table_regions_by_page=[])

    assert equations == []
    assert figures == [square]


def test_partition_equations_keeps_table_embedded_wide_image_as_a_figure():
    # A wide illustration inside a spec table's own cell (e.g. an assembly
    # cross-section) - table membership overrides the wide-shape heuristic.
    embedded = _image_asset(page=527, bbox=BBox(100.0, 100.0, 240.0, 126.0))
    table_regions_by_page = [[] for _ in range(527)]
    table_regions_by_page[526] = [_table_region_on_page(526, BBox(90.0, 90.0, 310.0, 310.0))]

    equations, figures = partition_equations([embedded], table_regions_by_page)

    assert equations == []
    assert figures == [embedded]


def test_main_exits_when_pdf_missing(tmp_path, monkeypatch):
    missing_pdf = str(tmp_path / "nope.pdf")
    monkeypatch.setattr(sys, "argv", ["build_mo_toc.py", missing_pdf])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert "No such file" in str(exc_info.value)
