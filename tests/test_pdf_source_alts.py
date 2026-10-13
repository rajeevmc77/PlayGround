"""PyMuPdfSource.page_image_alts: each image placement's structure-tree /Alt,
read from the page's marked content (/Figure <</MCID n>> BDC ... /ImX Do ...
EMC) and its /StructParents entry in the StructTreeRoot's /ParentTree."""

import io

import pymupdf as fitz
import pytest
from PIL import Image

from mo_toc.parsing.pdf_source import ImageAlt, PyMuPdfSource, image_placements

IMAGE_RECT = (20.0, 30.0, 120.0, 60.0)  # where the tests' page shows the image (MuPDF coords)
FIGURE_ELEMENT = "<< /Type /StructElem /S /Figure {alt} /Pg {page} 0 R /K 0 >>"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("1", (40, 12), 1).save(buf, format="PNG")
    return buf.getvalue()


def _new_object(doc, source: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, source)
    return xref


def _set_contents(doc, page, content: bytes) -> None:
    xref = _new_object(doc, "<<>>")
    doc.update_stream(xref, content)
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")


def _marked_image(name: str) -> bytes:
    # 100 x 30 pt at (20, 140) in PDF space: (20, 30, 120, 60) on a 200pt-tall page.
    return f"/Figure <</MCID 0 >>BDC q 100 0 0 30 20 140 cm /{name} Do Q EMC".encode()


def _page_with_image(doc):
    page = doc.new_page(width=200, height=200)
    page.insert_image(fitz.Rect(*IMAGE_RECT), stream=_png())
    return page, page.get_images(full=True)[0][7]


def _tag(doc, page, alt: str, parent_tree: str) -> tuple[int, int]:
    """Tags the page's MCID 0 with a /Figure element; gives (figure, parent tree) xrefs."""
    figure = _new_object(doc, FIGURE_ELEMENT.format(alt=alt, page=page.xref))
    tree = _new_object(doc, parent_tree.format(figure=figure))
    root = _new_object(doc, f"<< /Type /StructTreeRoot /K {figure} 0 R /ParentTree {tree} 0 R >>")
    doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")
    doc.xref_set_key(page.xref, "StructParents", "0")
    return figure, tree


def _tagged_doc():
    doc = fitz.open()
    page, name = _page_with_image(doc)
    _set_contents(doc, page, _marked_image(name))
    return doc, page


def _tagged_pdf(
    tmp_path,
    alt="/Alt (EQUATION)",
    parent_tree="<< /Nums [ 0 [ {figure} 0 R ] ] >>",
    content=None,
) -> str:
    doc = fitz.open()
    page, name = _page_with_image(doc)
    _set_contents(doc, page, content if content is not None else _marked_image(name))
    _tag(doc, page, alt, parent_tree)
    path = str(tmp_path / "tagged.pdf")
    doc.save(path)
    return path


def _assert_one_alt_at_the_image(alts: list[ImageAlt], alt: str) -> None:
    assert [a.alt for a in alts] == [alt]
    assert alts[0].bbox == pytest.approx(IMAGE_RECT, abs=0.01)


def test_a_tagged_image_gets_its_alt_where_the_page_draws_it(tmp_path):
    source = PyMuPdfSource(_tagged_pdf(tmp_path))

    alts = source.page_image_alts(0)

    _assert_one_alt_at_the_image(alts, "EQUATION")
    assert alts[0].bbox == pytest.approx(source.page_images(0)[0].bbox, abs=0.01)


def test_any_other_alt_text_is_given_verbatim(tmp_path):
    path = _tagged_pdf(tmp_path, alt="/Alt (C:\\\\figs\\\\fig-1.eps)")

    _assert_one_alt_at_the_image(PyMuPdfSource(path).page_image_alts(0), "C:\\figs\\fig-1.eps")


def test_an_empty_alt_is_given_as_an_empty_string(tmp_path):
    path = _tagged_pdf(tmp_path, alt="/Alt ()")

    _assert_one_alt_at_the_image(PyMuPdfSource(path).page_image_alts(0), "")


def test_a_structure_element_without_an_alt_gives_nothing(tmp_path):
    assert PyMuPdfSource(_tagged_pdf(tmp_path, alt="")).page_image_alts(0) == []


def test_an_untagged_pdf_gives_no_alts(tmp_path):
    doc = fitz.open()
    _page_with_image(doc)
    path = str(tmp_path / "untagged.pdf")
    doc.save(path)

    assert PyMuPdfSource(path).page_image_alts(0) == []


def test_a_page_with_no_struct_parents_entry_gives_no_alts(tmp_path):
    doc = fitz.open(_tagged_pdf(tmp_path))
    doc.xref_set_key(doc[0].xref, "StructParents", "null")
    path = str(tmp_path / "no_struct_parents.pdf")
    doc.save(path)

    assert PyMuPdfSource(path).page_image_alts(0) == []


def test_a_marked_content_id_with_no_structure_element_gives_nothing(tmp_path):
    path = _tagged_pdf(tmp_path, parent_tree="<< /Nums [ 0 [ null ] ] >>")

    assert PyMuPdfSource(path).page_image_alts(0) == []


def test_an_image_drawn_outside_marked_content_gives_nothing(tmp_path):
    content = b"q 100 0 0 30 20 140 cm /Img0 Do Q"

    assert PyMuPdfSource(_tagged_pdf(tmp_path, content=content)).page_image_alts(0) == []


def test_a_parent_tree_split_into_kids_is_searched_by_their_limits(tmp_path):
    doc, page = _tagged_doc()
    figure, tree = _tag(doc, page, "/Alt (EQUATION)", "<< >>")
    other = _new_object(doc, "<< /Limits [ 5 9 ] /Nums [ 5 [ null ] ] >>")
    leaf = _new_object(doc, f"<< /Limits [ 0 4 ] /Nums [ 0 [ {figure} 0 R ] ] >>")
    doc.update_object(tree, f"<< /Kids [ {other} 0 R {leaf} 0 R ] >>")
    path = str(tmp_path / "kids.pdf")
    doc.save(path)

    _assert_one_alt_at_the_image(PyMuPdfSource(path).page_image_alts(0), "EQUATION")


def test_a_parent_tree_entry_held_as_a_separate_array_object_is_read(tmp_path):
    doc, page = _tagged_doc()
    figure, tree = _tag(doc, page, "/Alt (EQUATION)", "<< >>")
    array = _new_object(doc, f"[ {figure} 0 R ]")
    doc.update_object(tree, f"<< /Nums [ 0 {array} 0 R ] >>")
    path = str(tmp_path / "array_object.pdf")
    doc.save(path)

    _assert_one_alt_at_the_image(PyMuPdfSource(path).page_image_alts(0), "EQUATION")


@pytest.mark.parametrize(
    "parent_tree",
    [
        "<< /Nums (not an array) >>",
        "<< /Kids [ 99999 0 R ] >>",
        "<< /Kids [ {figure} 0 R ] >>",
        "<< /Nums [ 0 ] >>",
        "(not a dictionary)",
    ],
)
def test_a_malformed_parent_tree_gives_no_alts_instead_of_failing(tmp_path, parent_tree):
    assert PyMuPdfSource(_tagged_pdf(tmp_path, parent_tree=parent_tree)).page_image_alts(0) == []


def test_a_parent_tree_whose_kids_loop_back_on_it_gives_no_alts(tmp_path):
    doc, page = _tagged_doc()
    _figure, tree = _tag(doc, page, "/Alt (EQUATION)", "<< >>")
    doc.update_object(tree, f"<< /Kids [ {tree} 0 R ] >>")
    path = str(tmp_path / "cycle.pdf")
    doc.save(path)

    assert PyMuPdfSource(path).page_image_alts(0) == []


@pytest.mark.parametrize(
    "content",
    [
        b"\x00\xff((( q Q Q Q EMC EMC 1 2 cm /Img0 Do",
        b"/Figure <</MCID 0 >>BDC q a b c d e f cm /Img0 Do Q EMC",
        b"/Figure <</MCID x >>BDC q 1 0 0 1 0 0 cm /Img0 Do Q EMC",
    ],
)
def test_a_malformed_content_stream_gives_no_alts_instead_of_failing(tmp_path, content):
    assert PyMuPdfSource(_tagged_pdf(tmp_path, content=content)).page_image_alts(0) == []


# image_placements: the pure content-stream reading behind page_image_alts.


def test_a_placement_records_the_transform_composed_through_nested_q_blocks():
    content = b"q 2 0 0 2 10 10 cm q 50 0 0 20 0 0 cm /Im0 Do Q Q"

    assert image_placements(content) == [((100.0, 0.0, 0.0, 40.0, 10.0, 10.0), None)]


def test_operator_words_in_a_comment_are_not_read():
    content = b"% q 2 0 0 2 0 0 cm /Im9 Do\n/Im0 Do"

    assert image_placements(content) == [((1.0, 0.0, 0.0, 1.0, 0.0, 0.0), None)]


def test_restoring_the_graphics_state_undoes_a_transform():
    content = b"q 2 0 0 2 0 0 cm Q 1 0 0 1 5 5 cm /Im0 Do"

    assert image_placements(content) == [((1.0, 0.0, 0.0, 1.0, 5.0, 5.0), None)]


def test_a_placement_takes_the_innermost_marked_content_id():
    content = b"/Figure <</MCID 7 >>BDC /Span BMC /Im0 Do EMC EMC /Im1 Do"

    assert [mcid for _, mcid in image_placements(content)] == [7, None]


def test_operator_words_inside_strings_and_inline_images_are_not_read():
    content = b"(q (nested) \\) Q Do) Tj BI /W 1 /H 1 ID \x00 Do q\xff EI /Im0 Do"

    assert image_placements(content) == [((1.0, 0.0, 0.0, 1.0, 0.0, 0.0), None)]


def test_unbalanced_restores_and_marked_content_ends_are_ignored():
    content = b"Q EMC Q /Im0 Do"

    assert image_placements(content) == [((1.0, 0.0, 0.0, 1.0, 0.0, 0.0), None)]


def test_empty_content_has_no_placements():
    assert image_placements(b"") == []
