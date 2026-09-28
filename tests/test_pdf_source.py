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


@pytest.fixture
def pdf_with_coloured_rules(tmp_path):
    """Real case: page 60's Table 1.3.1.2. has blue underlines under the
    cross-references in its last column; the grid read them as row rules."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(90, 100, 520, 100.7), color=None, fill=(0, 0, 0))  # black rule
    page.draw_rect(fitz.Rect(90, 140, 520, 140.7), color=None, fill=(0.14, 0.12, 0.13))  # grey
    page.draw_rect(fitz.Rect(399, 120, 437, 120.6), color=None, fill=(0, 0, 1))  # blue underline
    page.draw_line((90, 160), (520, 160), color=(0, 0, 0))  # stroked, not filled
    path = tmp_path / "rules.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_page_rule_rects_keep_black_and_grey_rules_but_not_coloured_ones(pdf_with_coloured_rules):
    source = PyMuPdfSource(pdf_with_coloured_rules)

    tops = sorted(round(rect[1]) for rect in source.page_rule_rects(0))

    assert tops == [100, 140, 160]


def test_page_drawing_rects_still_include_coloured_drawings(pdf_with_coloured_rules):
    # Vector figures are clustered from every drawing, coloured or not.
    assert len(PyMuPdfSource(pdf_with_coloured_rules).page_drawing_rects(0)) == 4


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


def _centred_line_pdf(tmp_path, page_width):
    doc = fitz.open()
    page = doc.new_page(width=page_width, height=792)
    text = "Table 9.8.4.2."
    x = (page_width - fitz.get_text_length(text, fontname="helv", fontsize=10)) / 2
    page.insert_text((x, 100), text, fontname="helv", fontsize=10)
    page.insert_text((72, 140), "Table 1.3.1.2. is referenced here", fontname="helv", fontsize=10)
    path = tmp_path / "centred.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.mark.parametrize("page_width", [612, 792])
def test_page_lines_mark_a_line_centred_on_its_page(tmp_path, page_width):
    lines = PyMuPdfSource(_centred_line_pdf(tmp_path, page_width)).page_lines(0)

    assert [(line.text, line.centred) for line in lines] == [
        ("Table 9.8.4.2.", True),
        ("Table 1.3.1.2. is referenced here", False),
    ]


def test_a_line_read_without_its_page_width_is_not_centred():
    assert _line_from_span_dict(_line_dict(_span("word", "BookAntiqua"))).centred is False


def test_a_line_records_where_each_of_its_spans_sits():
    # Table 3.2.3.1.-B's "1.2", "1.5", ... each head a narrow column but
    # arrive as one line; their spans say where each one is.
    first = {**_span(" 1.2", "BookAntiqua"), "bbox": (186, 0, 197, 10)}
    blank = {**_span(" ", "BookAntiqua"), "bbox": (197, 0, 199, 10)}
    second = {**_span("1.5 ", "BookAntiqua"), "bbox": (206, 0, 216, 10)}
    line = _line_from_span_dict(_line_dict(first, blank, second))
    assert line.text == "1.21.5"
    assert line.runs == ((0, 3, 186, 197), (3, 6, 206, 216))


def test_a_line_whose_spans_have_no_boxes_records_no_runs():
    assert _line_from_span_dict(_line_dict(_span("word", "BookAntiqua"))).runs == ()


def test_page_images_report_whether_the_page_draws_an_image_flipped(tmp_path):
    # The A-9.32.3.4 figures (pp. 1491-1495) are drawn with a negative
    # height: the page shows them upside down relative to how they're stored.
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), (255, 0, 0)).save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(10, 10, 60, 60), stream=buf.getvalue(), rotate=180)
    page.insert_image(fitz.Rect(100, 10, 160, 60), stream=buf.getvalue())
    path = tmp_path / "flipped.pdf"
    doc.save(str(path))
    flipped, upright = PyMuPdfSource(str(path)).page_images(0)
    assert (flipped.flipped_x, flipped.flipped_y) == (True, True)
    assert (upright.flipped_x, upright.flipped_y) == (False, False)
