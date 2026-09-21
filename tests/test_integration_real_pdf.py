from pathlib import Path

import pytest

from mo_toc.output.image_writer import write_images
from mo_toc.parsing.image_extractor import extract_images
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.pdf_source import PyMuPdfSource
from mo_toc.parsing.tree_builder import build_tree

PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "MO Package BCBC MRK signed.pdf"


@pytest.mark.slow
def test_division_a_starts_on_page_6():
    volume, _captions = build_tree(PyMuPdfSource(str(PDF_PATH)))
    division_a = next(c for c in volume.children if c.type == "Division" and c.identifier == "A")
    assert division_a.page == 6


@pytest.mark.slow
def test_appendix_c_and_d_sit_between_division_b_and_c():
    volume, _captions = build_tree(PyMuPdfSource(str(PDF_PATH)))
    order = [c.type + c.identifier for c in volume.children if c.type in ("Division", "Appendix")]
    assert order.index("DivisionB") < order.index("AppendixC") < order.index("DivisionC")
    assert order.index("AppendixC") < order.index("AppendixD") < order.index("DivisionC")


@pytest.mark.slow
def test_backmatter_starts_around_page_1675():
    volume, _captions = build_tree(PyMuPdfSource(str(PDF_PATH)))
    back_matter = next(c for c in volume.children if c.type == "BackMatter")
    assert 1670 <= back_matter.page <= 1680


@pytest.mark.slow
def test_part_4_wind_load_diagrams_get_matched_to_their_multi_line_caption(tmp_path):
    # Confirmed real-document case: Figure 4.1.7.6.-A on page 516 (and the
    # same Part 4 wind-load pattern on 518-524, 529-530, 533) has a caption
    # whose title wraps across two more lines plus a "Forming Part of
    # Sentence ..." line before the diagram starts. Measuring the gap from
    # only the "Figure ..." identifier line's own bbox (rather than the
    # full caption block) put the true ~57pt distance just over
    # MAX_CAPTION_GAP, leaving these diagrams uncaptioned.
    source = PyMuPdfSource(str(PDF_PATH))
    volume, captions = build_tree(source)
    raw_images = extract_images(source)
    images = write_images(raw_images, str(tmp_path / "images"))
    matched = match_images(images, captions, volume)

    expected = {
        516: "4.1.7.6.-A",
        518: "4.1.7.6.-B",
        529: "4.1.7.12.-A",
        533: "4.1.7.13.-B",
    }
    by_page = {img.page: img for img in matched if img.page in expected}
    for page, identifier in expected.items():
        assert by_page[page].caption_identifier == identifier, page
