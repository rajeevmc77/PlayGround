import pytest

from mo_toc.domain.models import BBox, Caption, Node
from mo_toc.parsing.pdf_source import PageLine
from mo_toc.parsing.table_extractor import (
    TableAnchor,
    TableRegion,
    attach_tables,
    build_continuation_region,
    detect_tables_on_page,
    fill_continuation_gaps,
    find_table_anchors,
    rects_form_a_grid,
    stitch_continuations,
)
from mo_toc.parsing.tree_builder import build_tree_from_lines

CAPTION_FONT = "Arial-BoldMT"
BODY_FONT = "ArialMT"
HEADING_FONT = "Arial-Black"


def pline(x0, y0, x1, y1, text, font=BODY_FONT):
    return PageLine(bbox=(x0, y0, x1, y1), text=text, font=font)


def _minimal_grid_fixture():
    lines = [
        pline(200, 10, 300, 20, "Table 1.1.(1)", CAPTION_FONT),
        pline(150, 22, 350, 32, "Sample Title", CAPTION_FONT),
        pline(90, 50, 110, 60, "No.", CAPTION_FONT),
        pline(120, 50, 250, 60, "Description", CAPTION_FONT),
        pline(90, 70, 110, 80, "1", BODY_FONT),
        pline(120, 70, 250, 80, "First row content.", BODY_FONT),
    ]
    rects = [
        (90.0, 45.0, 260.0, 45.4),  # top border
        (90.0, 45.0, 90.4, 90.0),  # left border
        (259.6, 45.0, 260.0, 90.0),  # right border
        (90.0, 65.0, 260.0, 65.4),  # header/body divider
        (90.0, 89.6, 260.0, 90.0),  # bottom border
        (114.6, 45.0, 115.0, 90.0),  # column divider
    ]
    return lines, rects


def test_find_table_anchors_finds_identifier():
    lines, _ = _minimal_grid_fixture()
    anchors = find_table_anchors(lines, page_index=6)
    assert len(anchors) == 1
    assert anchors[0].identifier == "1.1.(1)"
    assert anchors[0].caption_line_idx == 0


def test_find_table_anchors_ignores_figure_captions():
    lines = [pline(200, 10, 300, 20, "Figure 1.1.(1)", CAPTION_FONT)]
    assert find_table_anchors(lines, page_index=6) == []


def test_detect_tables_on_page_builds_header_and_data_row():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    assert len(regions) == 1
    table = regions[0].table_node
    assert table.type == "Table"
    assert table.citation == "Table:1.1.(1)"
    assert table.page == 7
    header, data = table.children
    assert header.type == "Row"
    assert [c.content for c in header.children] == ["No.", "Description"]
    assert [c.content for c in data.children] == ["1", "First row content."]


def test_detect_tables_on_page_assigns_citations_by_position():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    header, data = regions[0].table_node.children
    assert header.citation == "Table:1.1.(1)-Row1"
    assert data.citation == "Table:1.1.(1)-Row2"
    assert data.children[0].citation == "Table:1.1.(1)-Row2-Col1"
    assert data.children[1].citation == "Table:1.1.(1)-Row2-Col2"


def test_detect_tables_on_page_marks_consumed_line_indices():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    # caption trigger (0) + the descriptive title line (1) + the 4
    # cell-content lines (2,3,4,5). Corrected from an earlier assumption
    # that tree_builder's own caption dispatch would separately exclude the
    # title line (1) - it never does, because the caption trigger line (0)
    # is already consumed by the time tree_builder sees it, so
    # tree_builder._process_page skips straight past it without ever
    # calling _open_caption. table_extractor.py must consume the title
    # line itself, or it leaks into whatever Sentence/Clause/Subclause is
    # currently open as body content (see
    # test_detect_tables_on_page_does_not_leak_title_into_consumed_content
    # below for the direct proof).
    assert regions[0].consumed_line_indices == {0, 1, 2, 3, 4, 5}


def _heading_lines_opening_a_sentence():
    # Mirrors test_tree_builder.py's own Part/Compliance/Section/Subsection/
    # Article/marker-line shape (test_consumed_line_indices_are_excluded_
    # from_article_body), placed at y-coordinates well above the table
    # grid's own row band (45-90) so none of them are ever miscounted as
    # table cell content by _assign_lines_to_cells.
    return [
        pline(40, -300, 340, -290, "Part 1", HEADING_FONT),
        pline(40, -280, 340, -270, "Compliance", HEADING_FONT),
        pline(40, -260, 340, -250, "Section  1.1.   General", HEADING_FONT),
        pline(40, -240, 340, -230, "1.1.1. Application", HEADING_FONT),
        pline(40, -220, 340, -210, "1.1.1.1. Application of this Code", HEADING_FONT),
        pline(40, -200, 340, -190, "1) Real sentence text.", BODY_FONT),
    ]


def test_detect_tables_on_page_does_not_leak_title_into_consumed_content():
    # Direct, cross-module proof that the leak the dispatcher flagged is
    # closed: feeds detect_tables_on_page's own consumed_line_indices
    # (which now include the title line) into tree_builder.build_tree_from_
    # lines, the same wiring build_mo_toc.py's run() uses, and confirms the
    # table's descriptive title text never reaches the Sentence that's open
    # when the table's caption appears.
    table_lines, rects = _minimal_grid_fixture()
    lines = _heading_lines_opening_a_sentence() + table_lines

    regions = detect_tables_on_page(lines, rects, page_number=1)
    assert len(regions) == 1

    volume, _captions = build_tree_from_lines(
        [lines], 1, consumed_by_page={0: regions[0].consumed_line_indices}
    )
    article = volume.children[0].children[0].children[0].children[0].children[0]
    sentence = article.children[0]
    assert sentence.type == "Sentence"
    assert "Real sentence text." in sentence.content
    assert "Sample Title" not in sentence.content
    assert "No." not in sentence.content
    assert "First row content." not in sentence.content


def test_detect_tables_on_page_returns_nothing_below_minimum_grid_size():
    lines = [
        pline(200, 10, 300, 20, "Table 1.1.(1)", CAPTION_FONT),
        pline(90, 50, 110, 60, "Only one column, no real grid.", BODY_FONT),
    ]
    rects = [(90.0, 45.0, 260.0, 45.4)]  # a single thin rule line, not a grid
    assert detect_tables_on_page(lines, rects, page_number=7) == []


def _header_only_grid_fixture():
    # Mirrors the real document's page-794 Table 9.10.14.5.-A: the anchor
    # page holds only a header band bordered top and bottom - a single
    # row-boundary pair, no internal row divider - because the data rows
    # continue on the next page under a caption-less grid of their own.
    lines = [
        pline(200, 10, 300, 20, "Table 1.1.(1)", CAPTION_FONT),
        pline(90, 50, 110, 60, "No.", CAPTION_FONT),
        pline(120, 50, 250, 60, "Description", CAPTION_FONT),
    ]
    rects = [
        (90.0, 45.0, 260.0, 45.4),  # top border
        (90.0, 45.0, 90.4, 65.0),  # left border
        (259.6, 45.0, 260.0, 65.0),  # right border
        (90.0, 64.6, 260.0, 65.0),  # bottom border
        (114.6, 45.0, 115.0, 65.0),  # column divider
    ]
    return lines, rects


def test_detect_tables_on_page_accepts_header_only_single_row_grid_on_anchor_page():
    lines, rects = _header_only_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=794)
    assert len(regions) == 1
    table = regions[0].table_node
    assert len(table.children) == 1
    header = table.children[0]
    assert [c.content for c in header.children] == ["No.", "Description"]


def test_detect_tables_on_page_captures_forming_part_of_line():
    lines, rects = _minimal_grid_fixture()
    lines.insert(2, pline(150, 34, 350, 44, "Forming part of Sentence 1.1.1.1.(1)", BODY_FONT))
    regions = detect_tables_on_page(lines, rects, page_number=7)
    assert regions[0].forming_part_of == ("Sentence", "1.1.1.1.(1)")
    assert 2 in regions[0].consumed_line_indices


def test_detect_tables_on_page_forming_part_of_absent_when_no_match():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    assert regions[0].forming_part_of is None


def test_cell_content_joins_multiple_physical_lines_in_one_cell():
    lines, rects = _minimal_grid_fixture()
    lines.append(pline(120, 82, 250, 88, "continues wrapping.", BODY_FONT))
    rects[4] = (90.0, 92.0, 260.0, 92.4)  # push the bottom border down to fit the extra line
    rects[1] = (90.0, 45.0, 90.4, 92.0)
    rects[2] = (259.6, 45.0, 260.0, 92.0)
    rects[5] = (114.6, 45.0, 115.0, 92.0)
    regions = detect_tables_on_page(lines, rects, page_number=7)
    data_row = regions[0].table_node.children[1]
    assert data_row.children[1].content == "First row content. continues wrapping."


def test_cell_emphasis_follows_its_lines_into_the_joined_content():
    lines, rects = _minimal_grid_fixture()
    lines[5] = PageLine(
        bbox=(120, 70, 250, 80), text="First row content.", font=BODY_FONT, emphasis=((6, 9, "i"),)
    )
    regions = detect_tables_on_page(lines, rects, page_number=7)
    header_row, data_row = regions[0].table_node.children
    assert data_row.children[1].emphasis == [(6, 9, "i")]
    assert header_row.children[0].emphasis == []


def _table_region(identifier, page, rows, has_bottom_border, outer_bbox, forming_part_of=None):
    anchor = TableAnchor(page_index=page - 1, caption_line_idx=0, identifier=identifier)
    table_node = Node(
        type="Table",
        identifier=identifier,
        citation=f"Table:{identifier}",
        title="",
        page=page,
        end_page=page,
        bbox=outer_bbox,
        children=rows,
    )
    return TableRegion(
        anchor=anchor,
        table_node=table_node,
        forming_part_of=forming_part_of,
        consumed_line_indices=set(),
        has_bottom_border=has_bottom_border,
        outer_bbox=outer_bbox,
    )


def _row(identifier, cells):
    return Node(
        type="Row",
        identifier=identifier,
        citation=f"r-{identifier}",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
        children=cells,
    )


def _cell(identifier, content):
    return Node(
        type="Cell",
        identifier=identifier,
        citation=f"c-{identifier}",
        title="",
        content=content,
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )


def test_stitch_continuations_merges_open_table_across_pages():
    row1 = _row("Row1", [_cell("Col1", "a"), _cell("Col2", "b")])
    page1_region = _table_region(
        "1.1.(1)", page=8, rows=[row1], has_bottom_border=False, outer_bbox=BBox(90, 400, 500, 700)
    )
    row2 = _row("Row1", [_cell("Col1", "c"), _cell("Col2", "d")])
    page2_region = _table_region(
        "1.1.(1)", page=9, rows=[row2], has_bottom_border=True, outer_bbox=BBox(90, 40, 500, 200)
    )
    stitched = stitch_continuations([[page1_region], [page2_region]])
    assert len(stitched) == 1
    table = stitched[0].table_node
    assert len(table.children) == 2
    assert table.children[1].identifier == "Row2"
    assert table.children[1].children[0].citation == "Table:1.1.(1)-Row2-Col1"
    assert table.end_page == 9


def test_stitch_continuations_keeps_closed_table_separate_from_next_one():
    row1 = _row("Row1", [_cell("Col1", "a")])
    page1_region = _table_region(
        "1.1.(1)", page=8, rows=[row1], has_bottom_border=True, outer_bbox=BBox(90, 400, 500, 700)
    )
    row2 = _row("Row1", [_cell("Col1", "x")])
    page2_region = _table_region(
        "1.1.(2)", page=9, rows=[row2], has_bottom_border=True, outer_bbox=BBox(90, 40, 500, 200)
    )
    stitched = stitch_continuations([[page1_region], [page2_region]])
    assert len(stitched) == 2


def test_attach_tables_resolves_owner_by_identifier_matching_a_citation():
    sentence = Node(
        type="Sentence",
        identifier="(5)",
        citation="A-1.1.1.1.(5)",
        title="",
        content="Sentence text.",
        page=8,
        end_page=8,
        bbox=BBox(0, 100, 0, 0),
    )
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
        children=[sentence],
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    region = _table_region(
        "1.1.1.1.(5)",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    attach_tables(volume, [region])
    assert len(sentence.children) == 1
    assert sentence.children[0].citation == "Table:1.1.1.1.(5)"


def test_attach_tables_falls_back_to_forming_part_of_line():
    sentence = Node(
        type="Sentence",
        identifier="(5)",
        citation="A-1.1.1.1.(5)",
        title="",
        content="Sentence text.",
        page=8,
        end_page=8,
        bbox=BBox(0, 100, 0, 0),
    )
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
        children=[sentence],
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    # identifier "1.1.(9)-A" doesn't match any citation directly - only the
    # "Forming part of Sentence 1.1.1.1.(5)" line resolves the true owner.
    region = _table_region(
        "1.1.(9)-A",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
        forming_part_of=("Sentence", "1.1.1.1.(5)"),
    )
    attach_tables(volume, [region])
    assert len(sentence.children) == 1


def test_attach_tables_falls_back_to_position_when_neither_resolves():
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    region = _table_region(
        "unresolvable-id",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    attach_tables(volume, [region])
    assert len(article.children) == 1
    assert article.children[0].citation == "Table:unresolvable-id"


def _table_caption(identifier, title):
    return Caption(
        kind="Table",
        identifier=identifier,
        title=title,
        page=8,
        bbox=BBox(0, 0, 0, 0),
        owner_citation="",
        forming_part_of=None,
        continuation=False,
    )


def test_attach_tables_sets_title_from_matching_caption():
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    region = _table_region(
        "1.1.1.1.(5)",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    caption = _table_caption("1.1.1.1.(5)", "Alternate Compliance Methods for Heritage Buildings")
    attach_tables(volume, [region], [caption])
    assert article.children[0].title == "Alternate Compliance Methods for Heritage Buildings"


def test_attach_tables_leaves_title_empty_when_no_caption_matches():
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    region = _table_region(
        "1.1.1.1.(5)",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    other_caption = _table_caption("9.9.(9)", "Unrelated Table")
    attach_tables(volume, [region], [other_caption])
    assert article.children[0].title == ""
    # also confirm the no-captions-arg call path keeps working unchanged
    region2 = _table_region(
        "1.1.1.1.(5)",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    attach_tables(volume, [region2])
    assert article.children[1].title == ""


def test_attach_tables_does_not_clobber_a_good_title_with_an_empty_caption_title():
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    region = _table_region(
        "1.1.1.1.(5)",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    # build_table_region already set this geometrically-local title; a
    # matching caption whose OWN title happens to be blank must not clobber
    # it with an empty string.
    region.table_node.title = "Geometrically Local Title"
    blank_title_caption = _table_caption("1.1.1.1.(5)", "")
    attach_tables(volume, [region], [blank_title_caption])
    assert article.children[0].title == "Geometrically Local Title"


def test_attach_tables_raises_on_duplicate_table_citation_in_one_call():
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="Title",
        page=8,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[article],
    )
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=30,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )
    # Simulates the documented, currently-latent x-range-drift risk: two
    # distinct TableRegions (e.g. from a stitching failure) resolving to the
    # same citation within the SAME attach_tables() call.
    region1 = _table_region(
        "1.1.1.1.(5)",
        page=8,
        rows=[_row("Row1", [_cell("Col1", "a")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 200, 500, 300),
    )
    region2 = _table_region(
        "1.1.1.1.(5)",
        page=9,
        rows=[_row("Row1", [_cell("Col1", "b")])],
        has_bottom_border=True,
        outer_bbox=BBox(90, 40, 500, 200),
    )
    with pytest.raises(ValueError, match="Table:1.1.1.1.\\(5\\)"):
        attach_tables(volume, [region1, region2])
    # The duplicate-citation check must run BEFORE the offending region is
    # appended to its owner's children, so a raised ValueError never leaves
    # the tree partially mutated with the rejected, duplicate-citation node
    # already attached.
    assert len(article.children) == 1
    assert article.children[0] is region1.table_node


def _pending_region(cols=2, x_range=(90.0, 260.0), has_bottom_border=False):
    cells = [_cell(f"Col{i + 1}", f"v{i}") for i in range(cols)]
    row = _row("Row1", cells)
    anchor = TableAnchor(page_index=6, caption_line_idx=0, identifier="1.1.(1)")
    table_node = Node(
        type="Table",
        identifier="1.1.(1)",
        citation="Table:1.1.(1)",
        title="",
        page=7,
        end_page=7,
        bbox=BBox(x_range[0], 400, x_range[1], 700),
        children=[row],
    )
    return TableRegion(
        anchor=anchor,
        table_node=table_node,
        forming_part_of=None,
        consumed_line_indices=set(),
        has_bottom_border=has_bottom_border,
        outer_bbox=BBox(x_range[0], 400, x_range[1], 700),
    )


def _continuation_grid_fixture(x0=90.0, x1=260.0, div_x=175.0, closing=True):
    lines = [
        pline(x0 + 10, 50, x0 + 40, 60, "continued row 1 col a"),
        pline(div_x + 10, 50, x1 - 10, 60, "continued row 1 col b"),
    ]
    bottom_y = 70.0
    rects = [
        (x0, 45.0, x1, 45.4),
        (x0, 45.0, x0 + 0.4, bottom_y),
        (x1 - 0.4, 45.0, x1, bottom_y),
        (div_x, 45.0, div_x + 0.4, bottom_y),
    ]
    if closing:
        rects.append((x0, bottom_y - 0.4, x1, bottom_y))
    return lines, rects


def test_build_continuation_region_matches_pending_shape_and_x_range():
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    lines, rects = _continuation_grid_fixture()
    region = build_continuation_region(lines, rects, page_number=8, pending=pending)
    assert region is not None
    assert len(region.table_node.children) == 1
    assert [c.content for c in region.table_node.children[0].children] == [
        "continued row 1 col a",
        "continued row 1 col b",
    ]
    assert region.has_bottom_border is True


def test_build_continuation_region_rejects_when_no_grid_present():
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    lines = [pline(100, 50, 200, 60, "just some ordinary body text")]
    assert build_continuation_region(lines, [], page_number=8, pending=pending) is None


def test_build_continuation_region_rejects_column_count_mismatch():
    pending = _pending_region(cols=3, x_range=(90.0, 260.0))
    lines, rects = _continuation_grid_fixture()  # only 2 columns
    assert build_continuation_region(lines, rects, page_number=8, pending=pending) is None


def test_build_continuation_region_rejects_x_range_mismatch():
    # different table, elsewhere on the page
    pending = _pending_region(cols=2, x_range=(300.0, 470.0))
    lines, rects = _continuation_grid_fixture()  # x0=90, x1=260
    assert build_continuation_region(lines, rects, page_number=8, pending=pending) is None


def test_build_continuation_region_rejects_when_candidate_has_a_conflicting_forming_part_of_line():
    # Real-PDF-confirmed case (pages 169/170): Table 3.2.2.53.'s own anchor
    # page carries "Forming Part of Sentence 3.2.2.53.(1)". Page 170 - a
    # genuinely different, unrelated Table 3.2.2.54. whose own "Table X"
    # caption trigger detect_tables_on_page missed - nonetheless matches
    # 3.2.2.53.'s column count and x-range (this document uses consistent
    # margins across all its tables), but carries its OWN "Forming Part of
    # Sentence 3.2.2.54.(1)" line. That disagreeing reference is a strong,
    # cheap signal this is a new table, not a continuation, even though the
    # shape coincidentally matches.
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    pending.forming_part_of = ("Sentence", "1.1.(1)")
    lines, rects = _continuation_grid_fixture()
    lines = [pline(100, 20, 300, 30, "Forming part of Sentence 9.9.(9)"), *lines]
    assert build_continuation_region(lines, rects, page_number=8, pending=pending) is None


def test_build_continuation_region_accepts_when_forming_part_of_agrees():
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    pending.forming_part_of = ("Sentence", "1.1.(1)")
    lines, rects = _continuation_grid_fixture()
    lines = [pline(100, 20, 300, 30, "Forming part of Sentence 1.1.(1)"), *lines]
    region = build_continuation_region(lines, rects, page_number=8, pending=pending)
    assert region is not None


def test_build_continuation_region_rejects_via_identifier_fallback_when_no_forming_part_of():
    # Direct unit coverage for the fallback branch specifically: pending's
    # ORIGINAL anchor never had a "Forming part of ..." line at all
    # (forming_part_of stays None), so the comparison falls back to
    # pending's own table identifier ("1.1.(1)" for _pending_region's
    # default) rather than a real forming-part-of reference.
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    assert pending.forming_part_of is None
    lines, rects = _continuation_grid_fixture()
    lines = [pline(100, 20, 300, 30, "Forming part of Sentence 9.9.(9)"), *lines]
    assert build_continuation_region(lines, rects, page_number=8, pending=pending) is None


def test_build_continuation_region_rejects_when_candidate_has_its_own_leading_title_block():
    # Real-PDF-confirmed case (page 835): sibling table families (e.g.
    # Table 9.15.4.5.-A/-B/-C) all share the SAME "Forming part of Sentence
    # 9.15.4.5.(2)" reference, so forming-part-of agreement alone cannot
    # tell a genuinely new sibling table apart from a real continuation.
    # The new sibling's own page nonetheless has its own bold-caption-font
    # descriptive title sitting directly above its grid - something a true
    # continuation page never has, since there is nothing to title.
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    pending.forming_part_of = ("Sentence", "1.1.(1)")
    lines, rects = _continuation_grid_fixture()
    lines = [
        pline(100, 5, 300, 15, "A Brand New Table's Own Descriptive Title", CAPTION_FONT),
        pline(100, 20, 300, 30, "Forming part of Sentence 1.1.(1)"),  # agrees, yet still rejected
        *lines,
    ]
    assert build_continuation_region(lines, rects, page_number=8, pending=pending) is None


def test_build_continuation_region_accepts_ordinary_body_text_above_the_grid():
    # A real continuation page can have ordinary, non-caption-font body
    # text sitting above its grid (e.g. wrapped text bleeding over from a
    # neighboring column) - this must not be mistaken for a leading title
    # block just because something happens to precede the grid.
    pending = _pending_region(cols=2, x_range=(90.0, 260.0))
    lines, rects = _continuation_grid_fixture()
    lines = [pline(100, 20, 300, 30, "ordinary wrapped body text"), *lines]
    region = build_continuation_region(lines, rects, page_number=8, pending=pending)
    assert region is not None


def test_fill_continuation_gaps_synthesizes_into_empty_page_slot():
    pending = _pending_region(has_bottom_border=False)
    lines, rects = _continuation_grid_fixture(closing=True)
    filled = fill_continuation_gaps(
        all_lines=[[], lines], all_drawing_rects=[[], rects], regions_by_page=[[pending], []]
    )
    assert len(filled[1]) == 1
    assert filled[1][0].has_bottom_border is True


def test_fill_continuation_gaps_leaves_empty_page_alone_when_nothing_pending():
    filled = fill_continuation_gaps(all_lines=[[]], all_drawing_rects=[[]], regions_by_page=[[]])
    assert filled == [[]]


def test_fill_continuation_gaps_rejects_candidate_when_preceding_page_has_an_orphaned_anchor():
    # Real-PDF-confirmed case (page 916): the preceding page (915) carries
    # TWO table captions, but only the first's grid actually fits there -
    # the second's caption/title/header appear, but its real data grid
    # does not, so detect_tables_on_page returns only 1 region there even
    # though find_table_anchors finds 2 anchors. That orphaned second
    # table's own grid then lands on the NEXT (candidate) page with
    # nothing of its own for _forming_part_of_conflicts or
    # _has_leading_title_block to see - it must be rejected regardless of
    # whether its shape happens to coincidentally match whatever else was
    # pending.
    minimal_lines, minimal_rects = _minimal_grid_fixture()
    orphan_caption = pline(200, 100, 300, 110, "Table 9.9.(9)", CAPTION_FONT)
    preceding_page_lines = [*minimal_lines, orphan_caption]
    preceding_page_regions = detect_tables_on_page(
        preceding_page_lines, minimal_rects, page_number=1
    )
    assert len(preceding_page_regions) == 1  # only "Table 1.1.(1)" got a region
    assert len(find_table_anchors(preceding_page_lines, page_index=0)) == 2

    candidate_lines, candidate_rects = _continuation_grid_fixture()  # same 2-col, x=90-260 shape
    filled = fill_continuation_gaps(
        all_lines=[preceding_page_lines, candidate_lines],
        all_drawing_rects=[minimal_rects, candidate_rects],
        regions_by_page=[preceding_page_regions, []],
    )
    assert filled[1] == []


def test_stitch_continuations_after_fill_continuation_gaps_merges_all_rows():
    pending = _pending_region(has_bottom_border=False)
    lines, rects = _continuation_grid_fixture(closing=True)
    filled = fill_continuation_gaps(
        all_lines=[[], lines], all_drawing_rects=[[], rects], regions_by_page=[[pending], []]
    )
    stitched = stitch_continuations(filled)
    assert len(stitched) == 1
    table = stitched[0].table_node
    assert len(table.children) == 2  # original Row1 + the continuation's Row2
    assert table.children[1].citation == "Table:1.1.(1)-Row2"


def test_fill_continuation_gaps_corrects_pending_border_when_page_box_closed_per_page():
    # Real-PDF-confirmed case (Table 1.1.1.1.(5), page 8): the source PDF
    # redraws a fully bordered box around each page's own fragment of a
    # still-continuing table, so a page-local has_bottom_border=True does
    # NOT mean the logical table closed there. fill_continuation_gaps must
    # correct the earlier region's has_bottom_border once a continuation is
    # confirmed on the very next page, since the existing (unmodified)
    # stitch_continuations/_continues_previous still gates purely on that
    # flag and would otherwise wrongly treat the table as already closed.
    pending = _pending_region(has_bottom_border=True)
    lines, rects = _continuation_grid_fixture(closing=True)
    filled = fill_continuation_gaps(
        all_lines=[[], lines], all_drawing_rects=[[], rects], regions_by_page=[[pending], []]
    )
    assert pending.has_bottom_border is False
    stitched = stitch_continuations(filled)
    assert len(stitched) == 1
    assert len(stitched[0].table_node.children) == 2


def _grid_rects(n_rows, n_cols, x0=90.0, y0=72.0, col_width=100.0, row_height=20.0):
    x1 = x0 + n_cols * col_width
    y1 = y0 + n_rows * row_height
    rects = []
    for row in range(n_rows + 1):
        y = y0 + row * row_height
        rects.append((x0, y, x1, y + 0.4))
    for col in range(n_cols + 1):
        x = x0 + col * col_width
        rects.append((x, y0, x + 0.4, y1))
    return rects


def test_rects_form_a_grid_true_for_a_real_multi_row_multi_col_grid():
    # Mirrors the real bug (Table 1.1.1.1.(5)'s continuation tail, page 12):
    # a caption-less cluster of thin gridline rects with no text at all can
    # still be recognized as "table-shaped" from geometry alone.
    assert rects_form_a_grid(_grid_rects(n_rows=4, n_cols=3)) is True


def test_rects_form_a_grid_false_for_a_plain_rectangle_outline():
    # A simple 4-sided box (a diagram border, or a single-cell frame) has
    # only one row-band and one column-band - not a grid.
    outline = [
        (90.0, 72.0, 260.0, 72.4),
        (90.0, 150.0, 260.0, 150.4),
        (90.0, 72.0, 90.4, 150.0),
        (259.6, 72.0, 260.0, 150.0),
    ]
    assert rects_form_a_grid(outline) is False


def test_rects_form_a_grid_false_for_empty_rects():
    assert rects_form_a_grid([]) is False
