from web_toc.parsing.note_extractor import extract_notes

APPENDIX = {
    "id": "nbc.divA.part1.appendix",
    "type": "part_appendix",
    "application_notes": [
        {
            "id": "nbc.divA.part1.appendix.appnote2",
            "type": "application_note",
            "number": "1.1.1.1.(3)",
            "title": "Factory-Constructed Buildings.",
            "content": [
                {"type": "paragraph", "id": "p1", "content": "The Code applies."},
                {
                    "type": "paragraph",
                    "id": "p2",
                    "content": "It covers:",
                    "lists": [{"type": "bulleted", "items": [{"id": "i1", "content": "suites,"}]}],
                },
                {"id": "f1", "type": "figure", "title": "Fig", "graphic": {"src": "x"}},
                {
                    "id": "t1",
                    "type": "table",
                    "title": "Tbl",
                    "structure": {"body_rows": [{"cells": [{"content": "cell text"}]}]},
                },
            ],
        },
        {
            "id": "nbc.divA.part1.appendix.appnote9",
            "type": "application_note",
            "title": "No number",
        },
    ],
}
OWNER = "nbc.divA.part1.appendix"


def test_extracts_note_with_official_number_owner_and_text():
    owner, note = extract_notes(APPENDIX, OWNER)[0]

    assert owner == "nbc.divA.part1.appendix"
    assert note.type == "Note"
    assert note.identifier == "A-1.1.1.1.(3)"
    assert note.heading == "A-1.1.1.1.(3)"
    assert note.citation == "nbc.divA.part1.appendix.appnote2"
    assert note.title == "Factory-Constructed Buildings."
    assert note.content == "The Code applies. It covers: suites,"


def test_note_without_number_gets_empty_identifier():
    _, note = extract_notes(APPENDIX, OWNER)[1]
    assert note.identifier == ""


def test_every_note_is_owned_by_the_fetching_node():
    owners = {owner for owner, _ in extract_notes(APPENDIX, OWNER)}
    assert owners == {OWNER}


def test_part10_note_is_owned_by_its_part_appendix_not_the_part():
    # nbc.divB.part10.appendix.appnote1 strips to nbc.divB.part10 (the Part);
    # the site groups it under the part_appendix whose content held it.
    content = {
        "id": "nbc.divB.part10.sect4.appendix",
        "application_notes": [
            {"id": "nbc.divB.part10.appendix.appnote1", "type": "application_note", "number": "10."}
        ],
    }
    owner, note = extract_notes(content, "nbc.divB.part10.sect4.appendix")[0]
    assert owner == "nbc.divB.part10.sect4.appendix"
    assert note.identifier == "A-10."


def test_note_without_id_is_skipped():
    content = {"application_notes": [{"type": "application_note", "number": "1."}]}
    assert extract_notes(content, OWNER) == []


def test_content_without_notes_yields_nothing():
    assert extract_notes({"id": "nbc.divA.part1.sect1"}, "x") == []
