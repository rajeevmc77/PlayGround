import io

import pymupdf as fitz
import pytest
from PIL import Image

from mo_toc.parsing.pdf_source import PyMuPdfSource, _line_from_span_dict


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


@pytest.fixture
def pdf_with_image(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (255, 0, 0)).save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(10, 10, 60, 60), stream=buf.getvalue())
    path = tmp_path / "with_image.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def pdf_with_vector_drawing(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 150, 150), color=(0, 0, 0), fill=(1, 1, 1))
    path = tmp_path / "with_drawing.pdf"
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


def test_extract_image_returns_raw_bytes_and_dimensions(pdf_with_image):
    source = PyMuPdfSource(pdf_with_image)
    infos = source.page_images(0)
    assert len(infos) == 1

    extracted = source.extract_image(infos[0].xref)

    assert extracted.data
    assert extracted.width > 0
    assert extracted.height > 0
    assert extracted.ext


def test_page_drawing_rects_empty_when_no_drawings(two_page_pdf):
    source = PyMuPdfSource(two_page_pdf)
    assert source.page_drawing_rects(0) == []


def test_page_drawing_rects_returns_bbox_of_each_path(pdf_with_vector_drawing):
    source = PyMuPdfSource(pdf_with_vector_drawing)
    rects = source.page_drawing_rects(0)
    assert len(rects) == 1
    assert rects[0] == pytest.approx((50, 50, 150, 150))


def test_render_region_returns_raster_bytes_at_requested_bbox(pdf_with_vector_drawing):
    source = PyMuPdfSource(pdf_with_vector_drawing)
    extracted = source.render_region(0, (50, 50, 150, 150))
    assert extracted.data
    assert extracted.ext == "png"
    assert extracted.width > 0
    assert extracted.height > 0


def _span(text, font, flags=0):
    return {"text": text, "font": font, "flags": flags}


def _line_dict(*spans):
    return {"bbox": (0, 0, 100, 10), "spans": list(spans)}


def test_a_line_records_its_italic_spans_as_emphasis():
    line = _line_from_span_dict(
        _line_dict(
            _span("a) a new ", "BookAntiqua"),
            _span("building", "BookAntiqua-Italic", flags=2),
            _span(", ", "BookAntiqua"),
        )
    )

    assert line.text == "a) a new building,"
    assert line.emphasis == ((9, 17, "i"),)
    assert line.styled.text == line.text


@pytest.mark.parametrize(
    ("font", "flags", "style"),
    [
        ("Arial-BoldMT", 16, "b"),
        ("Arial-Black", 0, "b"),
        ("Arial-BoldItalicMT", 18, "bi"),
        ("Helvetica-Oblique", 0, "i"),
        ("SomeFont", 2, "i"),
        ("BookAntiqua", 0, ""),
    ],
)
def test_bold_and_italic_come_from_the_font_name_or_its_flags(font, flags, style):
    line = _line_from_span_dict(_line_dict(_span("word", font, flags)))

    assert line.emphasis == (((0, 4, style),) if style else ())


def test_whitespace_only_spans_add_no_text_or_emphasis():
    line = _line_from_span_dict(
        _line_dict(_span("word", "BookAntiqua"), _span("   ", "BookAntiqua-Italic", 2))
    )

    assert line.text == "word"
    assert line.emphasis == ()


def test_page_lines_read_emphasis_from_a_real_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "plain", fontname="helv")
    page.insert_text((110, 72), "slanted", fontname="heit")
    path = tmp_path / "styled.pdf"
    doc.save(str(path))
    doc.close()

    lines = PyMuPdfSource(str(path)).page_lines(0)

    emphasised = [line.text[s:e] for line in lines for s, e, _ in line.emphasis]
    assert emphasised == ["slanted"]
