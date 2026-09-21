from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mo_toc.parsing.image_extractor import raster_images_on_page, vector_images_on_page
from mo_toc.parsing.pdf_source import PyMuPdfSource

PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "MO Package BCBC MRK signed.pdf"


def test_extract_page_matches_the_sequential_primitives_for_one_real_page():
    from mo_toc.parsing import parallel_extraction

    parallel_extraction._init_worker(str(PDF_PATH))

    lines, images = parallel_extraction._extract_page(0)

    source = PyMuPdfSource(str(PDF_PATH))
    expected_lines = source.page_lines(0)
    expected_raster = raster_images_on_page(source, 0)
    expected_vector = vector_images_on_page(source, 0, [r.bbox for r in expected_raster])

    assert lines == expected_lines
    assert images == expected_raster + expected_vector


@patch("mo_toc.parsing.parallel_extraction.ProcessPoolExecutor")
@patch("mo_toc.parsing.parallel_extraction.PyMuPdfSource")
def test_extract_all_pages_dispatches_one_task_per_page_and_merges_in_order(
    mock_source_cls, mock_executor_cls
):
    from mo_toc.parsing.parallel_extraction import _extract_page, _init_worker, extract_all_pages

    mock_source_cls.return_value.page_count = 3
    mock_executor = MagicMock()
    mock_executor_cls.return_value.__enter__.return_value = mock_executor
    mock_executor.map.return_value = [
        (["p0-line"], ["p0-image"]),
        (["p1-line"], []),
        ([], ["p2-image-a", "p2-image-b"]),
    ]

    all_lines, all_images = extract_all_pages("some.pdf", max_workers=4)

    mock_source_cls.assert_called_once_with("some.pdf")
    mock_executor_cls.assert_called_once_with(
        max_workers=4, initializer=_init_worker, initargs=("some.pdf",)
    )
    mock_executor.map.assert_called_once_with(_extract_page, range(3))
    assert all_lines == [["p0-line"], ["p1-line"], []]
    assert all_images == ["p0-image", "p2-image-a", "p2-image-b"]


@patch("mo_toc.parsing.parallel_extraction.ProcessPoolExecutor")
@patch("mo_toc.parsing.parallel_extraction.PyMuPdfSource")
def test_extract_all_pages_defaults_worker_count_to_cpu_count(mock_source_cls, mock_executor_cls):
    from mo_toc.parsing.parallel_extraction import extract_all_pages

    mock_source_cls.return_value.page_count = 0
    mock_executor = MagicMock()
    mock_executor_cls.return_value.__enter__.return_value = mock_executor
    mock_executor.map.return_value = []

    extract_all_pages("some.pdf")

    _, kwargs = mock_executor_cls.call_args
    assert kwargs["max_workers"] is None or kwargs["max_workers"] >= 1


@pytest.mark.slow
def test_parallel_extraction_matches_sequential_extraction_on_the_real_document():
    from mo_toc.parsing.image_extractor import extract_images
    from mo_toc.parsing.parallel_extraction import extract_all_pages
    from mo_toc.parsing.tree_builder import build_tree, build_tree_from_lines

    source = PyMuPdfSource(str(PDF_PATH))
    sequential_volume, sequential_captions = build_tree(source)
    sequential_images = extract_images(source)

    all_lines, parallel_images = extract_all_pages(str(PDF_PATH), max_workers=4)
    parallel_volume, parallel_captions = build_tree_from_lines(all_lines, len(all_lines))

    assert parallel_volume == sequential_volume
    assert parallel_captions == sequential_captions
    assert len(parallel_images) == len(sequential_images)
    assert {(img.page, img.bbox) for img in parallel_images} == {
        (img.page, img.bbox) for img in sequential_images
    }
