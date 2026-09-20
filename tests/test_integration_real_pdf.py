from pathlib import Path

import pytest

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
