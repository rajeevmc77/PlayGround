"""build_web_toc.py builds offline from what build_web_pages.py saved - these
tests lay out a tiny web_source/ + web_pages/ tree on disk and read back the
bcbc_web.json it writes."""

import json
from unittest.mock import patch

import pytest

from build_web_toc import _attach_notes, main, run
from web_toc.domain.models import WebNode

ROOT_XPATH = "/html/body/main/div/main"
SECTION = "nbc.divA.part1.sect1"
APPENDIX = "nbc.divA.part1.appendix"
SENTENCE = f"{SECTION}.subsect1.art1.sent1"
TABLE = f"{SECTION}.subsect1.art1.table1"
NOTE = f"{APPENDIX}.appnote1"

_NAV = {
    "tree": [
        {
            "id": "nbc.divA",
            "type": "division",
            "title": "Division A - Compliance",
            "path": "/code/nbc.divA",
            "children": [
                {
                    "id": "nbc.divA.part1",
                    "type": "part",
                    "number": "1",
                    "title": "Part 1 - Compliance",
                    "path": "/code/nbc.divA/1",
                    "children": [
                        {
                            "id": SECTION,
                            "type": "section",
                            "number": "1.1",
                            "title": "1.1. General",
                            "path": "/code/nbc.divA/1/1",
                            "children": [
                                {
                                    "id": f"{SECTION}.subsect1",
                                    "type": "subsection",
                                    "number": "1.1.1",
                                    "title": "1.1.1. Application",
                                    "path": "/code/nbc.divA/1/1/1",
                                    "children": [
                                        {
                                            "id": f"{SECTION}.subsect1.art1",
                                            "type": "article",
                                            "number": "1.1.1.1",
                                            "title": "1.1.1.1. Scope",
                                            "path": "/code/nbc.divA/1/1/1/1",
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": APPENDIX,
                            "type": "part_appendix",
                            "title": "Notes to Part 1",
                            "path": "/code/nbc.divA/1/appendix",
                        },
                    ],
                }
            ],
        }
    ]
}


def _cell(text):
    return {"content": [{"type": "text", "value": text}]}


_SECTION_CONTENT = {
    "id": SECTION,
    "content": [
        {
            "type": "sentence",
            "id": SENTENCE,
            "number": 1,
            "text": "See [REF:internal:x:shortNum].",
            "clauses": [{"id": f"{SENTENCE}.clause1", "letter": "a", "text": "[REF:y]"}],
        },
        {
            "type": "table",
            "id": TABLE,
            "title": "Nails",
            "structure": {
                "header_rows": [{"cells": [_cell("Provision")]}],
                "body_rows": [{"cells": [_cell("[REF:internal:z:shortNum]")]}],
            },
        },
        {"type": "figure", "id": f"{SECTION}.subsect1.art1.figure1", "graphic": {"src": "g/f1"}},
    ],
}

_APPENDIX_CONTENT = {
    "id": APPENDIX,
    "application_notes": [
        {
            "type": "application_note",
            "id": NOTE,
            "number": "1.1.1.1.(1)",
            "title": "Scope.",
            "content": [
                {"type": "text", "content": "Note body."},
                {
                    "type": "table",
                    "id": f"{NOTE}.table1",
                    "structure": {"header_rows": [], "body_rows": [{"cells": [_cell("n")]}]},
                },
            ],
        }
    ],
}


def _entry(xpath, text, y):
    return {
        "xpath": f"{ROOT_XPATH}/{xpath}",
        "text": text,
        "bbox": {"x0": 0.0, "y0": y, "x1": 100.0, "y1": y + 10},
    }


_SECTION_LAYOUT = {
    "elements": {
        SENTENCE: _entry("div[1]/div[2]", "(1) See 1.2.3.4.(2). (a) Article 9.1.2.1.", 40.0),
        f"{SENTENCE}.clause1": _entry("div[1]/div[2]/div[1]", "(a) Article 9.1.2.1.", 50.0),
        TABLE: _entry("div[1]/div[3]", "Provision 9.23.5.5. Roof Trusses", 60.0),
    },
    "tables": {
        TABLE: [
            {
                **_entry("div[1]/div[3]/table[1]/thead[1]/tr[1]", "Provision", 60.0),
                "cells": [_entry("div[1]/div[3]/table[1]/thead[1]/tr[1]/th[1]", "Provision", 60.0)],
            },
            {
                **_entry("div[1]/div[3]/table[1]/tbody[1]/tr[1]", "9.23.5.5.", 70.0),
                "cells": [
                    _entry(
                        "div[1]/div[3]/table[1]/tbody[1]/tr[1]/td[1]",
                        "9.23.5.5. Roof Trusses",
                        70.0,
                    )
                ],
            },
        ]
    },
    "images": [{"src": "/web-assets/g/f1.jpg", **_entry("div[1]/img[1]", "", 90.0)}],
    "headings": [
        _entry("h2[1]", "Section 1.1. General", 0.0),
        _entry("h3[1]", "1.1.1. Application", 10.0),
        _entry("h4[1]", "1.1.1.1. Scope", 20.0),
    ],
}


@pytest.fixture
def output_dir(tmp_path):
    source = tmp_path / "web_source"
    (source / "content").mkdir(parents=True)
    (source / "navigation.json").write_text(json.dumps(_NAV))
    (source / "snapshot.json").write_text(json.dumps({"version": "2024", "date": "2024-03-08"}))
    (source / "content" / f"{SECTION}.json").write_text(json.dumps(_SECTION_CONTENT))
    (source / "content" / f"{APPENDIX}.json").write_text(json.dumps(_APPENDIX_CONTENT))
    pages = tmp_path / "web_pages"
    pages.mkdir()
    (pages / f"{SECTION}.layout.json").write_text(json.dumps(_SECTION_LAYOUT))
    (tmp_path / "web_images").mkdir()
    (tmp_path / "web_images" / f"{SECTION}.subsect1.art1.figure1.jpg").write_bytes(b"jpg")
    return tmp_path


def _built(output_dir):
    run(str(output_dir))
    return json.loads((output_dir / "bcbc_web.json").read_text())


def _find(node, citation):
    if node["citation"] == citation:
        return node
    for child in node["children"]:
        found = _find(child, citation)
        if found is not None:
            return found
    return None


def test_run_builds_the_tree_tables_and_body_from_the_local_cache(output_dir):
    tree = _built(output_dir)["tree"]
    article = _find(tree, f"{SECTION}.subsect1.art1")
    # tables are attached before body text, as they always have been
    assert [child["type"] for child in article["children"]] == ["Table", "Sentence"]
    table = _find(tree, TABLE)
    assert [len(row["children"]) for row in table["children"]] == [1, 1]
    assert table["unified_number"].endswith(".Tbl1")
    assert _find(tree, f"{SENTENCE}.clause1")["unified_number"].endswith("(1)(a)")


def test_run_fills_rendered_text_and_locations_from_the_saved_layout(output_dir):
    tree = _built(output_dir)["tree"]
    sentence = _find(tree, SENTENCE)
    assert sentence["content"] == "(1) See 1.2.3.4.(2). (a) Article 9.1.2.1."
    assert sentence["location"] == {
        "page_file": f"web_pages/{SECTION}.html",
        "xpath": f"{ROOT_XPATH}/div[1]/div[2]",
        "bbox": {"x0": 0.0, "y0": 40.0, "x1": 100.0, "y1": 50.0},
    }
    cell = _find(tree, f"{TABLE}-row2-col1")
    assert cell["content"] == "9.23.5.5. Roof Trusses"
    assert cell["location"]["xpath"].endswith("tbody[1]/tr[1]/td[1]")
    assert _find(tree, f"{SECTION}.subsect1")["location"]["xpath"] == f"{ROOT_XPATH}/h3[1]"


def test_run_keeps_json_content_and_no_location_for_a_page_without_a_layout(output_dir, capsys):
    tree = _built(output_dir)["tree"]
    note = _find(tree, NOTE)
    assert note["content"] == "Note body."
    assert "location" not in note
    err = capsys.readouterr().err
    assert f"no layout for {APPENDIX}" in err
    assert "Sentence: 1 located, 0 unlocated" in err


def test_run_attaches_notes_before_resolving_their_tables(output_dir):
    tree = _built(output_dir)["tree"]
    note = _find(tree, NOTE)
    assert [child["citation"] for child in note["children"]] == [f"{NOTE}.table1"]


def test_run_points_images_at_their_local_file_and_location(output_dir):
    (image,) = _built(output_dir)["images"]
    assert image["local_path"] == f"web_images/{SECTION}.subsect1.art1.figure1.jpg"
    assert image["location"]["xpath"] == f"{ROOT_XPATH}/div[1]/img[1]"
    assert image["unified_number"]


def test_run_leaves_local_path_empty_for_an_image_that_was_never_downloaded(output_dir):
    (output_dir / "web_images" / f"{SECTION}.subsect1.art1.figure1.jpg").unlink()
    (image,) = _built(output_dir)["images"]
    assert image["local_path"] == ""


def test_run_skips_nodes_with_no_cached_content(output_dir):
    (output_dir / "web_source" / "content" / f"{SECTION}.json").unlink()
    tree = _built(output_dir)["tree"]
    assert _find(tree, SENTENCE) is None
    assert _find(tree, NOTE) is not None


def test_run_reads_revised_content_as_of_the_snapshot_date(output_dir):
    # As served, the row's current (2025) version is deleted - no cells; on
    # the 2024-03-08 snapshot date its original single cell applies.
    content = json.loads(json.dumps(_SECTION_CONTENT))
    content["content"][1]["structure"]["body_rows"] = [
        {
            "revised": True,
            "cells": [],
            "revisions": [
                {"type": "original", "effective_date": "2024-03-08", "cells": [_cell("orig")]},
                {"type": "revision", "effective_date": "2025-06-16", "deleted": True, "cells": []},
            ],
        }
    ]
    path = output_dir / "web_source" / "content" / f"{SECTION}.json"
    path.write_text(json.dumps(content))

    tree = _built(output_dir)["tree"]

    cell = _find(tree, f"{TABLE}-row2-col1")
    assert cell is not None
    assert cell["location"]["xpath"].endswith("tbody[1]/tr[1]/td[1]")


def test_main_builds_into_the_given_output_dir(output_dir, capsys):
    with patch("sys.argv", ["build_web_toc.py", "--output-dir", str(output_dir)]):
        main()
    assert (output_dir / "bcbc_web.json").exists()
    assert f"Wrote {output_dir}/bcbc_web.json" in capsys.readouterr().err


def test_run_without_a_cached_source_says_to_scrape_first(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_web_pages.py"):
        run(str(tmp_path))


def test_attach_notes_puts_part10_note_under_its_part_appendix():
    appendix = WebNode(
        type="part_appendix",
        identifier="",
        citation="nbc.divB.part10.sect4.appendix",
        title="",
        path="",
    )
    part = WebNode(
        type="part",
        identifier="10",
        citation="nbc.divB.part10",
        title="",
        path="",
        children=[appendix],
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[part])
    content = {
        "id": "nbc.divB.part10.sect4.appendix",
        "application_notes": [
            {"id": "nbc.divB.part10.appendix.appnote1", "type": "application_note", "number": "10."}
        ],
    }
    citations = {"root", "nbc.divB.part10", "nbc.divB.part10.sect4.appendix"}

    widened = _attach_notes(root, [(appendix, content)], citations)

    assert [c.citation for c in appendix.children] == ["nbc.divB.part10.appendix.appnote1"]
    assert [c.type for c in part.children] == ["part_appendix"]
    assert "nbc.divB.part10.appendix.appnote1" in widened
