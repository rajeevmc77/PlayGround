from web_toc.domain.models import WebNode
from web_toc.parsing.table_extractor import attach_tables, extract_tables, table_row_counts


def _real_shaped_table(table_id="nbc.divBV2.part9.sect23.subsect3.art1.table1"):
    return {
        "id": table_id,
        "type": "table",
        "title": "Diameter of Nails",
        "structure": {
            "header_rows": [
                {
                    "id": f"{table_id}.rowh1",
                    "type": "header_row",
                    "cells": [
                        {"content": [{"type": "text", "value": "Length"}]},
                        {"content": [{"type": "text", "value": "Diameter"}]},
                    ],
                }
            ],
            "body_rows": [
                {
                    "id": f"{table_id}.row1",
                    "type": "body_row",
                    "cells": [
                        {"content": [{"type": "text", "value": "45"}]},
                        {"content": [{"type": "text", "value": "2.64"}]},
                    ],
                }
            ],
        },
    }


def test_table_matches_deepest_ancestor_citation():
    citations = {"nbc.divA.part1.sect1", "nbc.divA.part1.sect1.subsect1.art1"}
    content = {
        "id": "nbc.divA.part1.sect1",
        "subsections": [
            {
                "articles": [
                    {"content": [_real_shaped_table("nbc.divA.part1.sect1.subsect1.art1.table1")]}
                ]
            }
        ],
    }
    owned = extract_tables(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert len(owned) == 1
    owner, table_node = owned[0]
    assert owner == "nbc.divA.part1.sect1.subsect1.art1"
    assert table_node.type == "Table"
    assert table_node.title == "Diameter of Nails"


def test_table_falls_back_to_enclosing_node_when_no_deeper_match():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [_real_shaped_table("nbc.divA.part1.sect1.subsect9.art9.table1")]}
    owned = extract_tables(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert owned[0][0] == "nbc.divA.part1.sect1"


def test_table_builds_row_and_cell_children_with_text_content():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [_real_shaped_table("nbc.divA.part1.sect1.table1")]}
    _, table_node = extract_tables(content, citations, "nbc.divA.part1.sect1")[0]

    assert len(table_node.children) == 2  # 1 header row + 1 body row
    header_row, body_row = table_node.children
    assert header_row.type == "Row"
    assert [cell.content for cell in header_row.children] == ["Length", "Diameter"]
    assert body_row.type == "Row"
    assert [cell.content for cell in body_row.children] == ["45", "2.64"]
    assert all(cell.type == "Cell" for cell in body_row.children)


def test_table_identifier_is_its_own_trailing_id_segment():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [_real_shaped_table("nbc.divA.part1.sect1.table1")]}
    _, table_node = extract_tables(content, citations, "nbc.divA.part1.sect1")[0]
    assert table_node.identifier == "table1"
    assert table_node.citation == "nbc.divA.part1.sect1.table1"


def test_no_tables_returns_empty_list():
    content = {"id": "nbc.divA.part1.sect1", "subsections": []}
    assert extract_tables(content, {"nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1") == []


def test_table_without_id_is_skipped_not_crashed():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            {"type": "table", "title": "Malformed", "structure": {}},
            _real_shaped_table("nbc.divA.part1.sect1.table1"),
        ]
    }
    owned = extract_tables(content, citations, "nbc.divA.part1.sect1")
    assert len(owned) == 1
    assert owned[0][1].citation == "nbc.divA.part1.sect1.table1"


def test_multiple_tables_in_one_content_json_are_all_extracted():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            _real_shaped_table("nbc.divA.part1.sect1.tableA"),
            _real_shaped_table("nbc.divA.part1.sect1.tableB"),
        ]
    }
    owned = extract_tables(content, citations, "nbc.divA.part1.sect1")
    assert {table_node.citation for _, table_node in owned} == {
        "nbc.divA.part1.sect1.tableA",
        "nbc.divA.part1.sect1.tableB",
    }


def test_attach_tables_appends_each_table_under_its_owner_node():
    owner = WebNode(
        type="article", identifier="1", citation="nbc.divA.part1.sect1.art1", title="", path=""
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[owner])
    table_node = WebNode(
        type="Table",
        identifier="table1",
        citation="nbc.divA.part1.sect1.art1.table1",
        title="",
        path="",
    )

    attach_tables(root, [("nbc.divA.part1.sect1.art1", table_node)])

    assert owner.children == [table_node]


def test_attach_tables_ignores_a_table_whose_owner_citation_is_not_found():
    root = WebNode(type="root", identifier="", citation="root", title="", path="")
    table_node = WebNode(
        type="Table", identifier="table1", citation="missing.table1", title="", path=""
    )

    attach_tables(root, [("does.not.exist", table_node)])

    assert root.children == []


def test_extract_tables_reads_a_cell_whose_content_is_a_bare_string():
    # Some revision entries on the site give a cell's content as plain text.
    table = {
        "id": "t1",
        "type": "table",
        "structure": {"body_rows": [{"cells": [{"content": " See [REF:x] "}, {}]}]},
    }

    ((_, node),) = extract_tables(table, {"t1"}, "t1")

    assert [cell.content for cell in node.children[0].children] == ["See [REF:x]", ""]


def _rows_table(table_id, header_rows, body_rows):
    return {
        "id": table_id,
        "type": "table",
        "structure": {"header_rows": [{}] * header_rows, "body_rows": [{}] * body_rows},
    }


def test_table_row_counts_counts_header_and_body_rows_of_every_nested_table():
    content = {
        "articles": [
            {"content": [_rows_table("t1", 1, 3)]},
            {"sentences": [{"content": [_rows_table("t2", 0, 2)]}]},
        ]
    }

    assert table_row_counts(content) == {"t1": 4, "t2": 2}


def test_table_row_counts_skips_tables_without_an_id_or_structure():
    content = [{"type": "table"}, {"type": "table", "id": "t3"}]

    assert table_row_counts(content) == {"t3": 0}


def test_table_row_counts_of_empty_content_is_empty():
    assert table_row_counts({}) == {}
