import pymupdf as fitz
import pytest

from mo_toc.parsing.pdf_source import PyMuPdfSource


@pytest.fixture
def two_page_pdf(tmp_path):
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Hello World")
    _page2 = doc.new_page()
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_page_count(two_page_pdf):
    source = PyMuPdfSource(two_page_pdf)
    assert source.page_count == 2


def test_page_lines_returns_text_and_bbox(two_page_pdf):
    source = PyMuPdfSource(two_page_pdf)
    lines = source.page_lines(0)
    assert len(lines) == 1
    assert lines[0].text == "Hello World"
    assert len(lines[0].bbox) == 4
    assert lines[0].font  # non-empty


def test_page_lines_empty_page_returns_empty_list(two_page_pdf):
    source = PyMuPdfSource(two_page_pdf)
    assert source.page_lines(1) == []


def test_page_line_x0_y0_properties_match_bbox(two_page_pdf):
    source = PyMuPdfSource(two_page_pdf)
    line = source.page_lines(0)[0]
    assert (line.x0, line.y0) == (line.bbox[0], line.bbox[1])


def test_page_images_empty_when_no_images(two_page_pdf):
    source = PyMuPdfSource(two_page_pdf)
    assert source.page_images(0) == []
