import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from build_mo_toc import build_document
from mo_toc.output.image_writer import write_images
from mo_toc.parsing.image_extractor import extract_images
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.parallel_extraction import extract_all_pages
from mo_toc.parsing.pdf_source import PyMuPdfSource
from mo_toc.parsing.tree_builder import build_tree

PDF_PATH = Path(__file__).resolve().parent.parent / "data" / "MO Package BCBC MRK signed.pdf"


def _build_real_tree_with_tables():
    # Mirrors build_mo_toc.run's own orchestration via the shared
    # build_document() helper: build_tree alone (as the other tests in this
    # file use) never runs table detection/attachment - that's the separate
    # extract_all_pages + build_document step that build_mo_toc.py's run()
    # wires together. A table-attachment assertion needs the real pipeline,
    # not just build_tree.
    all_lines, _raw_images, table_regions_by_page, all_drawing_rects = extract_all_pages(
        str(PDF_PATH)
    )
    volume, captions, _table_regions_by_page = build_document(
        all_lines, table_regions_by_page, all_drawing_rects
    )
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
    # Compliance Methods for Heritage Buildings". table_extractor.py now
    # captures that title itself (_consume_table_title) and copies it onto
    # the Table node's own title (build_table_region), and separately
    # attach_tables can also pick it up from a matching Caption when one
    # exists - both fixed after this was found to always be "".
    assert table.title == "Alternate Compliance Methods for Heritage Buildings"
    # Confirmed real bug this also fixes: the sentence's own genuine prose
    # legitimately mentions this exact phrase once ("...the Alternate
    # Compliance Methods for Heritage Buildings in Table 1.1.1.1.(5) may be
    # substituted..."), so a blanket "not in" check would be wrong. Before
    # _consume_table_title's line range was added to build_table_region's
    # consumed_line_indices, the caption's own title line ALSO fell through
    # tree_builder's _append_to_current_article and got appended as a
    # second, standalone duplicate of this same phrase right after "(See
    # Note A-1.1.1.1.(5).)" - confirmed by direct inspection: this count
    # was 2 before the fix (the legitimate occurrence plus the leaked
    # duplicate) and is 1 after it.
    assert sentence.content.count("Alternate Compliance Methods for Heritage Buildings") == 1
    first_row = table.children[0]
    assert [c.content for c in first_row.children] == [
        "No.",
        "Code Requirement in Division B",
        "Alternate Compliance Method",
    ]


@pytest.mark.slow
def test_table_1_1_1_1_5_continuation_rows_are_captured_and_do_not_leak():
    # Confirmed real-document fact (corrected from Task 14's brief, whose
    # illustrative "37 rows" / "'Part 6 and Part 7' not in sentence.content"
    # numbers the brief itself flagged as unverified): Table 1.1.1.1.(5) is
    # a genuinely multi-page table spanning pages 8-11, with its 3-column
    # header ("No.", "Code Requirement in Division B", "Alternate
    # Compliance Method") plus 33 sequentially-numbered data rows (1
    # through 33) plus one cosmetic blank row-band (index 15, page 10 -
    # likely a spurious extra divider rect _grid_boundaries picked up) -
    # 35 Table children in total (1 + 33 + 1), versus just 5 (header +
    # rows 1-4) before this task's fix, when only page 8's own
    # caption-anchored grid was ever detected and pages 9-11 (which have no
    # "Table X" caption of their own) produced zero TableRegions.
    volume, _captions = _build_real_tree_with_tables()
    sentence = _find_by_citation(volume, "A-1.1.1.1.(5)")
    table = next(c for c in sentence.children if c.type == "Table")
    assert len(table.children) == 35
    assert table.page == 8
    assert table.end_page == 11

    # Locks in the known cosmetic extra row-band's actual content, so a
    # future regression is caught here instead of silently passing on a
    # merely higher row count. Correction from an earlier, less careful
    # inspection (this task's own first report draft called this row
    # "fully blank, both cells ''"): direct re-inspection shows only the
    # first two cells are empty - the third genuinely contains real text,
    # a wrapped continuation of the PRECEDING row's own "Alternate
    # Compliance Method" cell that _grid_boundaries mistakenly split off
    # into its own row-band (a pre-existing row/column-band imprecision in
    # the geometry heuristic, not a new corruption introduced by this
    # task's continuation detection).
    spurious_row = table.children[15]
    assert len(spurious_row.children) == 3
    assert spurious_row.children[0].content == ""
    assert spurious_row.children[1].content == ""
    assert "smoke detectors" in spurious_row.children[2].content

    last_row = table.children[-1]
    assert last_row.children[0].content == "33"
    assert "Height of Rooms" in last_row.children[1].content
    assert "Existing rooms are not required to comply" in last_row.children[2].content

    # A representative middle row (page 9 - previously an empty page slot,
    # since it has no caption of its own) is now a proper structured
    # Row/Cell instead of loose text folded into the Sentence's own content.
    row_five = table.children[5]
    assert row_five.children[0].content == "5"
    assert "Rating of Supporting Construction" in row_five.children[1].content

    # Known, documented residual limitation (see task-14-report.md): rows
    # 34-37 sit on page 12, ABOVE Table 1.1.1.1.(6)'s own caption/grid on
    # that same page - a page that already has its own anchor-detected
    # region. A first attempt to capture that shared-page leading fragment
    # (bounding the rect scan to "everything above the next anchor's own
    # grid top") was reverted after real-PDF verification showed it
    # silently misfiled Sentence 1.1.1.1.(6)'s own introductory prose as
    # fake Table 1.1.1.1.(5) rows - a worse failure than the leak it
    # targeted, since there is no geometric signal in this document
    # distinguishing "one more continuation row" from "ordinary body text
    # sitting in the same gap". This assertion documents that residual
    # leak honestly rather than letting it silently regress further or be
    # silently claimed as fixed.
    assert "Part 6 and Part 7" in sentence.content


@pytest.mark.slow
def test_table_3_2_2_53_does_not_absorb_the_next_unrelated_table_as_fake_continuation_rows():
    # Reviewer-confirmed false positive (fixed by _forming_part_of_conflicts):
    # page 170 has zero of its own anchor-detected TableRegions (its own
    # "Table 3.2.2.54." caption trigger was never matched by
    # find_table_anchors - a separate, pre-existing gap this task does not
    # attempt to fix), yet its grid coincidentally shares Table 3.2.2.53.'s
    # column count and x-range (this document uses consistent margins
    # across all its tables). Before the forming-part-of guard, page 170
    # was silently absorbed as fake continuation rows of Table 3.2.2.53.
    # (confirmed: its own header row "No. of Storeys, Maximum Area, m2..."
    # would have been swallowed as a data row under the WRONG table's
    # citation). Table 3.2.2.53.'s own page carries "Forming Part of
    # Sentence 3.2.2.53.(1)"; page 170 carries a disagreeing "Forming Part
    # of Sentence 3.2.2.54.(1)" - the signal that now correctly rejects the
    # match.
    volume, _captions = _build_real_tree_with_tables()
    table = _find_by_citation(volume, "Table:3.2.2.53.")
    assert table is not None
    assert len(table.children) == 5
    assert table.page == 169
    assert table.end_page == 169
    last_row = table.children[-1]
    assert [c.content for c in last_row.children] == ["3", "800", "1000", "1200"]


@pytest.mark.slow
def test_table_9_15_4_5_b_does_not_absorb_a_sibling_tables_own_title_page():
    # Reviewer-confirmed false positive (fixed by _has_leading_title_block,
    # NOT by _forming_part_of_conflicts alone): Table 9.15.4.5.-B, -C are
    # sibling tables in the same family that all share the SAME "Forming
    # Part of Sentence 9.15.4.5.(2)" reference, so reference equality can't
    # tell them apart. Page 835 - Table 9.15.4.5.-C's own page, whose own
    # "Table X" caption trigger find_table_anchors never matched (a
    # separate, pre-existing gap, same shape as Table 3.2.2.54.'s above) -
    # nonetheless has its own bold-caption-font descriptive title ("Vertical
    # Reinforcement for 240 mm Flat Insulating Concrete Form Founda...")
    # sitting directly above its grid. Before this guard, page 835 was
    # silently absorbed as fake continuation rows of Table 9.15.4.5.-B,
    # header row and all.
    volume, _captions = _build_real_tree_with_tables()
    table = _find_by_citation(volume, "Table:9.15.4.5.-B")
    assert table is not None
    assert len(table.children) == 7
    assert table.page == 834
    assert table.end_page == 834
    last_row = table.children[-1]
    assert [c.content for c in last_row.children] == ["3.0", "n/a", "n/a", "15M at 400 mm o.c."]


@pytest.mark.slow
def test_table_9_24_2_1_correctly_merges_its_genuine_continuation_on_page_926():
    # CORRECTED from an earlier round's factual misdiagnosis: that round
    # believed page 926 was a 4th false positive and reverted a scan bound
    # to "fix" it. Direct re-inspection (confirmed by the reviewer, then
    # re-confirmed here) shows page 926 is NOT a false positive at all - it
    # is a genuine continuation of Table 9.24.2.1., with 10 real data rows
    # matching the table's own 3-column shape exactly ("600"/"2.7",
    # "300"/"4.4", "32 x 64"/"400"/"4.0", etc.). The earlier round's
    # "Forming Part of Sentence 9.24.2.5.(1)" concern was a real line, but
    # it sits at y=692 - hundreds of points below page 926's own grid,
    # which ends at y=243.12 - as part of an entirely unrelated later
    # table's own caption introduced by ordinary body prose further down
    # the SAME page. Bounding _own_forming_part_of_reference's scan to
    # strictly above the candidate's own grid top (as _forming_part_of_
    # above already does on an anchored page) correctly excludes that
    # distant, irrelevant line, so this genuine continuation is now
    # correctly accepted - restoring the originally-intended, and correct,
    # bounded behavior.
    volume, _captions = _build_real_tree_with_tables()
    table = _find_by_citation(volume, "Table:9.24.2.1.")
    assert table is not None
    assert len(table.children) == 12
    assert table.page == 925
    assert table.end_page == 926
    assert [c.content for c in table.children[1].children] == ["32 × 41", "400", "3.0"]
    last_row = table.children[-1]
    assert [c.content for c in last_row.children] == ["", "600", "4.9"]
    assert all(row.page == 925 for row in table.children[:2])
    assert all(row.page == 926 for row in table.children[2:])


@pytest.mark.slow
def test_table_9_23_13_11_c_does_not_absorb_the_next_tables_orphaned_grid():
    # Reviewer-confirmed 5th false-merge shape (fixed by
    # _preceding_page_has_orphaned_anchor): page 915 carries TWO table
    # captions, "Table 9.23.13.11.-C" and "Table 9.23.13.11.-D" - but only
    # C's grid fits there. D's own caption, title, forming-part-of line,
    # AND header row are all on page 915 too, but D's actual multi-row data
    # grid does not fit and spills onto page 916 with nothing of D's own
    # left there for _forming_part_of_conflicts or _has_leading_title_block
    # to see (both only ever inspect the CANDIDATE page, never the
    # preceding one). Before this guard, page 916 was silently absorbed as
    # fake continuation rows of Table 9.23.13.11.-C.
    volume, _captions = _build_real_tree_with_tables()
    table = _find_by_citation(volume, "Table:9.23.13.11.-C")
    assert table is not None
    assert len(table.children) == 8
    assert table.page == 915
    assert table.end_page == 915


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
