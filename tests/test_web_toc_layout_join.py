import pytest

from web_toc.domain.models import WebImage, WebNode
from web_toc.parsing.layout_join import GridMismatch, join_layout, location_report

ROOT = "/html/body/main/div/main"
SECTION = "nbc.divB.part9.sect38"
TABLE = f"{SECTION}.subsect1.art1.table1"
SENTENCE = f"{SECTION}.subsect1.art1.sent1"


def _box(n):
    return {"x0": 0.0, "y0": float(n), "x1": 10.0, "y1": float(n + 1)}


def _entry(xpath, text, n):
    return {"xpath": f"{ROOT}/{xpath}", "text": text, "bbox": _box(n)}


def _node(type_, citation, children=(), heading="", content=""):
    return WebNode(
        type=type_,
        identifier="",
        citation=citation,
        title="",
        path="",
        heading=heading,
        content=content,
        children=list(children),
    )


def _table_node(cells_per_row):
    rows = [
        _node(
            "Row",
            f"{TABLE}-row{r + 1}",
            [
                _node("Cell", f"{TABLE}-row{r + 1}-col{c + 1}", content="[REF:x]")
                for c in range(cells)
            ],
        )
        for r, cells in enumerate(cells_per_row)
    ]
    return _node("Table", TABLE, rows)


def _tree(table=None):
    sentence = _node(
        "Sentence",
        SENTENCE,
        [_node("Clause", f"{SENTENCE}.clause1", content="(a) [REF:y]")],
        content="(1) [REF:z]",
    )
    article = _node("article", f"{SECTION}.subsect1.art1", [sentence], heading="9.38.1.1")
    if table is not None:
        article.children.append(table)
    subsection = _node("subsection", f"{SECTION}.subsect1", [article], heading="9.38.1")
    section = _node("section", SECTION, [subsection], heading="9.38")
    part = _node("part", "nbc.divB.part9", [section], heading="Part 9")
    return _node("root", "root", [part])


def _layout(rows=((1, 2), (3,))):
    return {
        "elements": {
            SENTENCE: _entry("div[1]/div[2]", "(1) Resolved sentence (a) clause", 5),
            f"{SENTENCE}.clause1": _entry("div[1]/div[2]/div[1]", "(a) clause", 6),
            TABLE: _entry("div[1]/div[3]", "whole table", 7),
        },
        "tables": {
            TABLE: [
                {
                    **_entry(f"div[1]/div[3]/table[1]/tbody[1]/tr[{r + 1}]", "row", 10 + r),
                    "cells": [
                        _entry(
                            f"div[1]/div[3]/table[1]/tbody[1]/tr[{r + 1}]/td[{c}]", f"cell{c}", c
                        )
                        for c in row
                    ],
                }
                for r, row in enumerate(rows)
            ]
        },
        "images": [
            {"src": "/web-assets/bc-graphics/fig1.jpg", "text": "Fig", **_entry("img[1]", "", 20)}
        ],
        "headings": [
            _entry("h1[1]", "Part 9 - Housing and Small Buildings", 0),
            _entry("h2[1]", "Section 9.38. Objectives", 1),
            _entry("h3[1]", "9.38.1. Objectives", 2),
            _entry("h4[1]", "9.38.1.1. Attribution", 3),
        ],
    }


def _find(node, citation):
    if node.citation == citation:
        return node
    for child in node.children:
        found = _find(child, citation)
        if found is not None:
            return found
    return None


def _join(root, layouts, images=(), pages=(SECTION,)):
    join_layout(root, list(images), layouts, set(pages))
    return root


def test_an_id_matched_node_gets_its_page_file_xpath_bbox_and_rendered_text():
    root = _join(_tree(), {SECTION: _layout()})
    sentence = _find(root, SENTENCE)
    assert sentence.location == {
        "page_file": f"web_pages/{SECTION}.html",
        "xpath": f"{ROOT}/div[1]/div[2]",
        "bbox": _box(5),
    }
    assert sentence.content == "(1) Resolved sentence (a) clause"
    assert _find(root, f"{SENTENCE}.clause1").content == "(a) clause"


def test_rows_and_cells_are_matched_by_position_and_cells_get_rendered_text():
    root = _join(_tree(_table_node([2, 1])), {SECTION: _layout()})
    row2 = _find(root, f"{TABLE}-row2")
    cell = _find(root, f"{TABLE}-row1-col2")
    assert row2.location["xpath"] == f"{ROOT}/div[1]/div[3]/table[1]/tbody[1]/tr[2]"
    assert row2.location["bbox"] == _box(11)
    assert row2.content == ""  # a row has no text of its own
    assert cell.location["xpath"].endswith("tr[1]/td[2]")
    assert cell.content == "cell2"


def test_a_table_keeps_its_json_content_but_gets_a_location():
    root = _join(_tree(_table_node([2, 1])), {SECTION: _layout()})
    table = _find(root, TABLE)
    assert table.location["xpath"] == f"{ROOT}/div[1]/div[3]"
    assert table.content == ""


@pytest.mark.parametrize("cells_per_row", [[2], [2, 1, 1], [2, 2]])
def test_a_table_grid_that_differs_from_its_json_fails_loudly(cells_per_row):
    with pytest.raises(GridMismatch, match=TABLE):
        _join(_tree(_table_node(cells_per_row)), {SECTION: _layout()})


def test_headings_are_located_by_their_number_on_their_own_page():
    root = _join(
        _tree(),
        {SECTION: _layout(), "nbc.divB.part9": _layout()},
        pages=(SECTION, "nbc.divB.part9"),
    )
    assert _find(root, "nbc.divB.part9").location["xpath"] == f"{ROOT}/h1[1]"
    assert _find(root, SECTION).location["xpath"] == f"{ROOT}/h2[1]"
    assert _find(root, f"{SECTION}.subsect1").location["xpath"] == f"{ROOT}/h3[1]"
    assert _find(root, f"{SECTION}.subsect1.art1").location["xpath"] == f"{ROOT}/h4[1]"
    assert _find(root, f"{SECTION}.subsect1.art1").location["page_file"] == (
        f"web_pages/{SECTION}.html"
    )


def test_a_heading_number_does_not_match_a_longer_number_it_prefixes():
    layout = _layout()
    layout["headings"] = [_entry("h4[1]", "9.38.1.1. Attribution", 3)]
    root = _join(_tree(), {SECTION: layout})
    assert _find(root, f"{SECTION}.subsect1").location is None
    assert _find(root, f"{SECTION}.subsect1.art1").location is not None


def test_a_heading_level_node_without_a_heading_number_is_not_matched_by_text():
    root = _tree()
    _find(root, f"{SECTION}.subsect1").heading = ""
    _join(root, {SECTION: _layout()})
    assert _find(root, f"{SECTION}.subsect1").location is None


def test_a_table_with_no_measured_grid_is_located_but_its_rows_are_not():
    layout = _layout()
    del layout["tables"][TABLE]
    root = _join(_tree(_table_node([2, 1])), {SECTION: layout})
    assert _find(root, TABLE).location is not None
    assert _find(root, f"{TABLE}-row1").location is None


def test_an_image_is_located_by_its_src_on_its_owners_page():
    image = WebImage(id="f1", src="bc-graphics/fig1", alt_text="", owner_citation=SENTENCE)
    other = WebImage(id="f2", src="bc-graphics/other", alt_text="", owner_citation=SENTENCE)
    _join(_tree(), {SECTION: _layout()}, images=[image, other])
    assert image.location["xpath"] == f"{ROOT}/img[1]"
    assert image.location["page_file"] == f"web_pages/{SECTION}.html"
    assert other.location is None


def test_nodes_on_a_page_with_no_layout_keep_their_json_content_and_no_location():
    root = _join(_tree(_table_node([2, 1])), {})
    sentence = _find(root, SENTENCE)
    assert sentence.location is None
    assert sentence.content == "(1) [REF:z]"
    assert _find(root, f"{TABLE}-row1-col1").location is None


def test_nodes_above_any_page_are_left_unlocated():
    root = _join(_tree(), {SECTION: _layout()})
    assert _find(root, "nbc.divB.part9").location is None  # its page isn't a page target here


def test_location_report_counts_located_and_unlocated_nodes_and_images_by_type():
    image = WebImage(id="f1", src="bc-graphics/fig1", alt_text="", owner_citation=SENTENCE)
    root = _tree(_table_node([2, 1]))
    join_layout(root, [image], {SECTION: _layout()}, {SECTION})

    report = location_report(root, [image])

    assert report["Cell"] == {"located": 3, "unlocated": 0}
    assert report["Sentence"] == {"located": 1, "unlocated": 0}
    assert report["part"] == {"located": 0, "unlocated": 1}
    assert report["Image"] == {"located": 1, "unlocated": 0}
    assert "root" not in report
