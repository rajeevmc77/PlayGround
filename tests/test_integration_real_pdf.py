from pathlib import Path

import pytest

from mo_toc.output.image_writer import write_images
from mo_toc.parsing.image_extractor import extract_images
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.parallel_extraction import extract_all_pages
from mo_toc.parsing.pdf_source import PyMuPdfSource
from mo_toc.parsing.table_extractor import attach_tables, stitch_continuations
from mo_toc.parsing.tree_builder import build_tree, build_tree_from_lines

PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "MO Package BCBC MRK signed.pdf"


def _consumed_by_page(table_regions_by_page):
    return {
        page_index: {i for region in regions for i in region.consumed_line_indices}
        for page_index, regions in enumerate(table_regions_by_page)
        if regions
    }


def _build_real_tree_with_tables():
    # Mirrors build_mo_toc.run's own orchestration: build_tree alone (as the
    # other tests in this file use) never runs table detection/attachment -
    # that's a separate extract_all_pages + attach_tables/stitch_continuations
    # step that build_mo_toc.py wires together. A table-attachment assertion
    # needs the real pipeline, not just build_tree.
    all_lines, _raw_images, table_regions_by_page = extract_all_pages(str(PDF_PATH))
    volume, captions = build_tree_from_lines(
        all_lines, len(all_lines), consumed_by_page=_consumed_by_page(table_regions_by_page)
    )
    attach_tables(volume, stitch_continuations(table_regions_by_page))
    return volume, captions


def _find_by_citation(node, citation):
    if node.citation == citation:
        return node
    for child in node.children:
        found = _find_by_citation(child, citation)
        if found is not None:
            return found
    return None


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


@pytest.mark.slow
def test_clause_1_1_1_1_k_has_its_full_wrapped_text():
    # Confirmed bug this feature fixes: this clause's text used to cut off
    # mid-sentence at "...installation, replacement, or" because the second
    # physical line was silently dropped.
    volume, _captions = build_tree(PyMuPdfSource(str(PDF_PATH)))
    node = _find_by_citation(volume, "A-1.1.1.1.(1)(k)")
    assert node is not None
    assert node.content == (
        "except as permitted by the British Columbia Fire Code, the installation, "
        "replacement, or alteration of materials or equipment regulated by this Code,"
    )
    assert node.title == ""


@pytest.mark.slow
def test_table_1_1_1_1_5_is_attached_as_a_sentence_child_with_rows_and_cells():
    volume, _captions = _build_real_tree_with_tables()
    sentence = _find_by_citation(volume, "A-1.1.1.1.(5)")
    assert sentence is not None
    tables = [c for c in sentence.children if c.type == "Table"]
    assert len(tables) == 1
    table = tables[0]
    # Confirmed real-document text (page 8): the "Table 1.1.1.1.(5)" caption
    # is immediately followed by the descriptive title line "Alternate
    # Compliance Methods for Heritage Buildings". table_extractor.py's own
    # build_table_region always hard-codes title="" on the Table node
    # (confirmed at src/mo_toc/parsing/table_extractor.py:233, and matches
    # every Task 5/6 fixture) and nothing downstream (attach_tables,
    # json_writer.write_json) ever copies the matching
    # Caption(kind="Table").title captured by tree_builder's
    # _open_caption/_consume_caption_title back onto the Table node - even
    # though json_writer._prune_node deliberately keeps "title" for Table
    # nodes (unlike Row/Cell/Sentence/Clause/Subclause), implying it was
    # meant to carry this text. This assertion documents that real gap
    # rather than being weakened to match the current empty-string output.
    assert table.title == "Alternate Compliance Methods for Heritage Buildings"
    first_row = table.children[0]
    assert [c.content for c in first_row.children] == [
        "No.",
        "Code Requirement in Division B",
        "Alternate Compliance Method",
    ]


@pytest.mark.slow
def test_figure_a_1_1_1_1_6_has_a_formatted_title_and_note_level_owner(tmp_path):
    source = PyMuPdfSource(str(PDF_PATH))
    volume, captions = build_tree(source)
    raw_images = extract_images(source)
    images = write_images(raw_images, str(tmp_path / "images"))
    matched = match_images(images, captions, volume)

    figure = next(i for i in matched if i.caption_identifier == "A-1.1.1.1.(6)")
    assert figure.title == "Figure A-1.1.1.1.(6)"
    assert figure.owner_citation == "Note:A-1.1.1.1.(6)"
