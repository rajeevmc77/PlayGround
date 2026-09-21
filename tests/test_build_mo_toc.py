import sys
from unittest.mock import patch

import pytest

from build_mo_toc import main, run
from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)


@patch("build_mo_toc.write_json")
@patch("build_mo_toc.match_images")
@patch("build_mo_toc.write_images")
@patch("build_mo_toc.build_tree_from_lines")
@patch("build_mo_toc.assign_unified_numbers")
@patch("build_mo_toc.extract_all_pages")
def test_run_wires_pipeline_in_order(
    mock_extract_all_pages,
    mock_assign_numbers,
    mock_build_tree_from_lines,
    mock_write_images,
    mock_match_images,
    mock_write_json,
    tmp_path,
):
    mock_extract_all_pages.return_value = (["PAGE0_LINES", "PAGE1_LINES"], ["RAW_IMAGE"])
    mock_build_tree_from_lines.return_value = ("VOLUME", ["CAPTION"])
    mock_write_images.return_value = ["IMAGE_ASSET"]
    mock_match_images.return_value = ["MATCHED_IMAGE_ASSET"]

    run("some.pdf", str(tmp_path))

    mock_extract_all_pages.assert_called_once_with("some.pdf")
    mock_build_tree_from_lines.assert_called_once_with(["PAGE0_LINES", "PAGE1_LINES"], 2)
    mock_assign_numbers.assert_called_once_with(
        ["VOLUME"],
        MO_TOC_TYPE_MARKERS,
        identifier_types=MO_TOC_IDENTIFIER_TYPES,
        suffix_types=MO_TOC_SUFFIX_TYPES,
    )
    mock_write_images.assert_called_once_with(["RAW_IMAGE"], str(tmp_path / "images"))
    mock_match_images.assert_called_once_with(["IMAGE_ASSET"], ["CAPTION"], "VOLUME")
    mock_write_json.assert_called_once_with(
        "VOLUME", ["CAPTION"], ["MATCHED_IMAGE_ASSET"], str(tmp_path / "mo_toc.json")
    )


def test_main_exits_when_pdf_missing(tmp_path, monkeypatch):
    missing_pdf = str(tmp_path / "nope.pdf")
    monkeypatch.setattr(sys, "argv", ["build_mo_toc.py", missing_pdf])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert "No such file" in str(exc_info.value)
