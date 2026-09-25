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
CITATIONS = {"nbc.divA.part1.appendix"}


def test_extracts_note_with_official_number_owner_and_text():
    owner, note = extract_notes(APPENDIX, CITATIONS, "fallback")[0]

    assert owner == "nbc.divA.part1.appendix"
    assert note.type == "Note"
    assert note.identifier == "A-1.1.1.1.(3)"
    assert note.heading == "A-1.1.1.1.(3)"
    assert note.citation == "nbc.divA.part1.appendix.appnote2"
    assert note.title == "Factory-Constructed Buildings."
    assert note.content == "The Code applies. It covers: suites,"


def test_note_without_number_gets_empty_identifier():
    _, note = extract_notes(APPENDIX, CITATIONS, "fallback")[1]
    assert note.identifier == ""


def test_owner_falls_back_when_no_citation_matches():
    owner, _ = extract_notes(APPENDIX, set(), "fallback")[0]
    assert owner == "fallback"


def test_content_without_notes_yields_nothing():
    assert extract_notes({"id": "nbc.divA.part1.sect1"}, CITATIONS, "x") == []
