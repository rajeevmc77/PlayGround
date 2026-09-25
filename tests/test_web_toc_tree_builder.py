import pytest

from web_toc.parsing.tree_builder import build_tree, collect_citations, heading_for


def _nav_fixture():
    return {
        "tree": [
            {
                "id": "nbc.2020.vol1",
                "type": "volume",
                "number": "1",
                "title": "Volume 1",
                "path": "/volume/1",
                "children": [
                    {
                        "id": "nbc.divA",
                        "type": "division",
                        "title": "Division A",
                        "path": "/code/nbc.divA",
                        "children": [
                            {
                                "id": "nbc.divA.part1",
                                "type": "part",
                                "number": "1",
                                "title": "Part 1",
                                "path": "/code/nbc.divA/1",
                                "children": [
                                    {
                                        "id": "nbc.divA.part1.sect1",
                                        "type": "section",
                                        "number": "1.1",
                                        "title": "1.1 General",
                                        "path": "/code/nbc.divA/1/1",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "nbc.divBV2.part9",
                "type": "part",
                "number": "9",
                "title": "Part 9",
                "path": "/code/nbc.divBV2/9",
            },
        ]
    }


def test_build_tree_wraps_top_level_entries_under_a_root():
    root = build_tree(_nav_fixture())
    assert root.type == "root"
    assert len(root.children) == 2


def test_build_tree_preserves_nested_children():
    root = build_tree(_nav_fixture())
    volume = root.children[0]
    division = volume.children[0]
    part = division.children[0]
    section = part.children[0]
    types = [volume.type, division.type, part.type, section.type]
    expected_types = ["volume", "division", "part", "section"]
    assert types == expected_types
    assert section.citation == "nbc.divA.part1.sect1"
    assert section.identifier == "1.1"


def test_build_tree_derives_division_identifier_letter_from_title():
    root = build_tree(_nav_fixture())
    division = root.children[0].children[0]
    assert division.identifier == "A"


def test_build_tree_defaults_division_identifier_to_empty_when_title_has_no_letter():
    fixture = _nav_fixture()
    fixture["tree"][0]["children"][0]["title"] = "Untitled Division"
    root = build_tree(fixture)
    division = root.children[0].children[0]
    assert division.identifier == ""


def test_build_tree_defaults_identifier_to_empty_string_when_number_missing_on_non_division():
    fixture = _nav_fixture()
    del fixture["tree"][0]["children"][0]["children"][0]["number"]
    root = build_tree(fixture)
    part = root.children[0].children[0].children[0]
    assert part.type == "part"
    assert part.identifier == ""


def test_build_tree_leaf_node_has_no_children():
    root = build_tree(_nav_fixture())
    section = root.children[0].children[0].children[0].children[0]
    assert section.children == []


def test_collect_citations_includes_root_and_every_descendant():
    root = build_tree(_nav_fixture())
    citations = collect_citations(root)
    assert "root" in citations
    assert "nbc.divA.part1.sect1" in citations
    assert "nbc.divBV2.part9" in citations
    assert len(citations) == 6  # root + volume + division + part + section + part9


def test_collect_citations_on_leaf_node_returns_single_citation():
    root = build_tree(_nav_fixture())
    section = root.children[0].children[0].children[0].children[0]
    assert collect_citations(section) == {"nbc.divA.part1.sect1"}


@pytest.mark.parametrize(
    ("title", "heading"),
    [
        ("Part 1 - Compliance", "Part 1"),
        ("Division A - Compliance, Objectives and Functional Statements", "Division A"),
        ("Volume 2", "Volume 2"),
        ("Notes to Part 1", "Notes to Part 1"),
        ("10.1.1.1 Scope", "10.1.1.1"),
        ("10.1 General", "10.1"),
        ("Preface", ""),
        ("", ""),
    ],
)
def test_heading_for(title, heading):
    assert heading_for(title) == heading


def test_nav_nodes_get_heading_and_keep_verbatim_title():
    root = build_tree(
        {
            "tree": [
                {
                    "id": "nbc.divA.part1",
                    "type": "part",
                    "number": "1",
                    "title": "Part 1 - Compliance",
                    "path": "/x",
                }
            ]
        }
    )
    part = root.children[0]
    assert part.heading == "Part 1"
    assert part.title == "Part 1 - Compliance"
