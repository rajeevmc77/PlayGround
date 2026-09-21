from mo_toc.parsing.pdf_source import PageLine
from mo_toc.parsing.table_extractor import detect_tables_on_page, find_table_anchors

CAPTION_FONT = "Arial-BoldMT"
BODY_FONT = "ArialMT"


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
    # caption trigger (0) + the 4 cell-content lines (2,3,4,5); the
    # descriptive title line (1) is already excluded by tree_builder's
    # existing caption-title consumption, not by table_extractor.
    assert regions[0].consumed_line_indices == {0, 2, 3, 4, 5}


def test_detect_tables_on_page_returns_nothing_below_minimum_grid_size():
    lines = [
        pline(200, 10, 300, 20, "Table 1.1.(1)", CAPTION_FONT),
        pline(90, 50, 110, 60, "Only one column, no real grid.", BODY_FONT),
    ]
    rects = [(90.0, 45.0, 260.0, 45.4)]  # a single thin rule line, not a grid
    assert detect_tables_on_page(lines, rects, page_number=7) == []


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
