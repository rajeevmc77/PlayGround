import sys
from unittest.mock import MagicMock, patch

import pytest

from build_mo_toc import main, run
from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)


@patch("build_mo_toc.write_markdown")
@patch("build_mo_toc.write_json")
@patch("build_mo_toc.match_images")
@patch("build_mo_toc.write_thumbnails")
@patch("build_mo_toc.extract_images")
@patch("build_mo_toc.assign_unified_numbers")
@patch("build_mo_toc.build_tree")
@patch("build_mo_toc.PyMuPdfSource")
def test_run_wires_pipeline_in_order(
    mock_source_cls,
    mock_build_tree,
    mock_assign_numbers,
    mock_extract_images,
    mock_write_thumbs,
    mock_match_images,
    mock_write_json,
    mock_write_md,
    tmp_path,
):
    mock_source = MagicMock()
    mock_source_cls.return_value = mock_source
    mock_build_tree.return_value = ("VOLUME", ["CAPTION"])
    mock_extract_images.return_value = ["RAW_IMAGE"]
    mock_write_thumbs.return_value = ["IMAGE_ASSET"]
    mock_match_images.return_value = ["MATCHED_IMAGE_ASSET"]

    run("some.pdf", str(tmp_path))

    mock_source_cls.assert_called_once_with("some.pdf")
    mock_build_tree.assert_called_once_with(mock_source)
    mock_assign_numbers.assert_called_once_with(
        ["VOLUME"],
        MO_TOC_TYPE_MARKERS,
        identifier_types=MO_TOC_IDENTIFIER_TYPES,
        suffix_types=MO_TOC_SUFFIX_TYPES,
    )
    mock_extract_images.assert_called_once_with(mock_source)
    mock_write_thumbs.assert_called_once_with(["RAW_IMAGE"], str(tmp_path / "thumbnails"))
    mock_match_images.assert_called_once_with(["IMAGE_ASSET"], ["CAPTION"], "VOLUME")
    mock_write_json.assert_called_once_with(
        "VOLUME", ["CAPTION"], ["MATCHED_IMAGE_ASSET"], str(tmp_path / "mo_toc.json")
    )
    mock_write_md.assert_called_once_with("VOLUME", ["CAPTION"], str(tmp_path / "mo_toc.md"))


def test_main_exits_when_pdf_missing(tmp_path, monkeypatch):
    missing_pdf = str(tmp_path / "nope.pdf")
    monkeypatch.setattr(sys, "argv", ["build_mo_toc.py", missing_pdf])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert "No such file" in str(exc_info.value)
