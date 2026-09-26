import pytest

from web_toc.domain.models import WebImage, WebNode
from web_toc.parsing.layout_join import (
    GridMismatch,
    equation_images,
    join_layout,
    location_report,
)

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


def test_a_rendered_text_node_gets_the_emphasis_measured_with_its_text():
    layout = _layout()
    layout["elements"][f"{SENTENCE}.clause1"]["emphasis"] = [[4, 10, "i"]]
    root = _join(_tree(), {SECTION: layout})
    assert _find(root, f"{SENTENCE}.clause1").emphasis == [[4, 10, "i"]]
    assert _find(root, SENTENCE).emphasis == []  # measured without any


def test_a_heading_gets_a_location_but_no_emphasis():
    layout = _layout()
    layout["headings"][3]["emphasis"] = [[0, 8, "b"]]
    root = _join(_tree(), {SECTION: layout})
    assert _find(root, f"{SECTION}.subsect1.art1").emphasis == []


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


@pytest.mark.parametrize("cells_per_row", [[2], [2, 1, 1]])
def test_a_table_whose_row_count_differs_from_its_json_fails_loudly(cells_per_row):
    with pytest.raises(GridMismatch, match=TABLE):
        _join(_tree(_table_node(cells_per_row)), {SECTION: _layout()})


def _cells_row_table(*contents):
    """Row 1 has 2 cells (matching the layout); row 2 has the given contents."""
    table = _table_node([2, len(contents)])
    for cell, content in zip(table.children[1].children, contents, strict=True):
        cell.content = content
    return table


@pytest.mark.parametrize(
    ("contents", "located"),
    [
        (("", "[REF:x]"), [False, True]),  # a leading span placeholder
        (("[REF:x]", ""), [True, False]),  # a trailing one
        (("", "", "[REF:x]"), [False, False, True]),
    ],
)
def test_empty_json_cells_the_site_does_not_render_are_skipped(contents, located):
    root = _join(_tree(_cells_row_table(*contents)), {SECTION: _layout()})
    cells = _find(root, f"{TABLE}-row2").children
    assert [cell.location is not None for cell in cells] == located
    placed = next(cell for cell in cells if cell.location)
    assert placed.location["xpath"].endswith("tr[2]/td[3]")
    assert placed.content == "cell3"


def test_a_row_whose_non_empty_cells_cannot_all_be_paired_is_left_unlocated_and_reported():
    root = _tree(_cells_row_table("[REF:x]", "[REF:y]"))

    misaligned = join_layout(root, [], {SECTION: _layout()}, {SECTION})

    cells = _find(root, f"{TABLE}-row2").children
    assert [cell.location for cell in cells] == [None, None]
    assert _find(root, f"{TABLE}-row2").location is not None  # the row itself is placed
    assert misaligned == [f"{TABLE} row 2"]


def test_join_reports_no_misaligned_rows_when_every_row_pairs():
    assert join_layout(_tree(_table_node([2, 1])), [], {SECTION: _layout()}, {SECTION}) == []


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


def _equation(key, owner, n):
    return {"key": key, "owner": owner, **_entry(f"div[1]/div[2]/img[{n}]", f"eq {key}", 30 + n)}


def test_each_measured_equation_becomes_an_equation_image_owned_by_its_holder():
    layout = {"equations": [_equation("es1", f"{SENTENCE}.clause1", 1)]}

    [image] = equation_images({SECTION: layout}, {SENTENCE, f"{SENTENCE}.clause1"})

    assert (image.id, image.kind, image.alt_text) == ("es1", "equation", "eq es1")
    assert image.src == "equations/es1"
    assert image.owner_citation == f"{SENTENCE}.clause1"
    assert image.location == {
        "page_file": f"web_pages/{SECTION}.html",
        "xpath": f"{ROOT}/div[1]/div[2]/img[1]",
        "bbox": _box(31),
    }


def test_an_equation_holder_that_is_no_node_resolves_up_its_id_or_to_its_page():
    layout = {
        "equations": [
            _equation("n1", f"{SENTENCE}.para2", 1),  # a paragraph inside the sentence
            _equation(f"{SECTION}.eq1", "", 2),  # held by nothing with an id
        ]
    }

    images = equation_images({SECTION: layout}, {SENTENCE})

    assert [image.owner_citation for image in images] == [SENTENCE, SECTION]


def test_no_measured_equations_means_no_equation_images():
    assert equation_images({SECTION: _layout()}, {SENTENCE}) == []
    assert equation_images({}, {SENTENCE}) == []


def test_location_report_counts_equations_apart_from_figures():
    figure = WebImage(id="f1", src="", alt_text="", owner_citation=SENTENCE)
    equation = WebImage(id="e1", src="", alt_text="", owner_citation=SENTENCE, kind="equation")
    equation.location = {"page_file": "p", "xpath": "x", "bbox": _box(0)}

    report = location_report(_node("root", "root"), [figure, equation])

    assert report["Image"] == {"located": 0, "unlocated": 1}
    assert report["Equation"] == {"located": 1, "unlocated": 0}
