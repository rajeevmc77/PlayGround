import json

from compare_unified import (
    LevelCount,
    collect_keys,
    comparable_text,
    format_report,
    level_counts,
    main,
    text_mismatches,
)

PDF_TREE = {
    "type": "Volume",
    "unified_number": "V1",
    "children": [
        {
            "type": "Part",
            "unified_number": "A.1",
            "title": "Compliance",
            "heading": "Part 1",
            "children": [
                {
                    "type": "NotesContainer",
                    "unified_number": "A.1.Notes",
                    "title": "Notes to Part 1",
                    "heading": "Notes to Part 1",
                    "children": [],
                },
                {
                    "type": "Article",
                    "unified_number": "A.1.1.1.1",
                    "title": "Scope",
                    "children": [],
                },
            ],
        },
    ],
}
WEB_TREE = {
    "type": "root",
    "children": [
        {
            "type": "part",
            "unified_number": "A.1",
            "title": "Part 1 - Compliance",
            "heading": "Part 1",
            "children": [
                {
                    "type": "part_appendix",
                    "unified_number": "A.1.Notes",
                    "title": "Notes to Part 1",
                    "heading": "Notes to Part 1",
                    "children": [],
                },
                {
                    "type": "Sentence",
                    "unified_number": "A.1.1.1.1.(1)",
                    "content": "a [REF:term:bldng:building]",
                    "children": [],
                },
            ],
        },
    ],
}


def test_collect_keys_groups_by_level_and_skips_unnumbered():
    keys = collect_keys(PDF_TREE, [{"unified_number": "A.1.1.1.1.Fig1"}, {"unified_number": ""}])
    assert set(keys["part"]) == {"A.1"}
    assert set(keys["notes"]) == {"A.1.Notes"}
    assert set(keys["image"]) == {"A.1.1.1.1.Fig1"}
    assert keys["sentence"] == {}


def test_level_counts_both_and_only():
    pdf_keys = collect_keys(PDF_TREE, [])
    web_keys = collect_keys(WEB_TREE, [])
    counts = {c.level: c for c in level_counts(pdf_keys, web_keys)}
    assert counts["notes"] == LevelCount("notes", 1, 1, 1)
    assert (counts["article"].pdf_only, counts["article"].web_only) == (1, 0)
    assert (counts["sentence"].pdf_only, counts["sentence"].web_only) == (0, 1)


def test_comparable_text_strips_heading_refs_and_case():
    assert comparable_text({"title": "Part 1 - Compliance", "heading": "Part 1"}) == "compliance"
    assert comparable_text({"content": "A  [REF:term:bldng:Building]"}) == "a building"
    assert comparable_text({}) == ""


def test_comparable_text_keeps_full_text_when_stripping_heading_empties_it():
    node = {"title": "Notes to Part 1", "heading": "Notes to Part 1"}
    assert comparable_text(node) == "notes to part 1"


def test_text_mismatches_only_reports_matched_keys_that_differ():
    pdf = {"k1": {"title": "Scope"}, "k2": {"title": "X"}, "only": {"title": "Y"}}
    web = {"k1": {"title": "1.1.1.1 Scope", "heading": "1.1.1.1"}, "k2": {"title": "Z"}}
    assert text_mismatches(pdf, web) == [("k2", "x", "z")]


def test_text_mismatches_detects_different_note_titles():
    pdf = {"note_key": {"title": "Notes to Part 1", "heading": "Notes to Part 1"}}
    web = {"note_key": {"title": "Notes to Part 2", "heading": "Notes to Part 2"}}
    assert text_mismatches(pdf, web) == [("note_key", "notes to part 1", "notes to part 2")]


def test_format_report_has_header_and_one_row_per_level():
    report = format_report([LevelCount("part", 15, 15, 14)])
    lines = report.splitlines()
    assert lines[0].split() == ["level", "pdf", "web", "both", "pdf-only", "web-only"]
    assert lines[1].split() == ["part", "15", "15", "14", "1", "1"]


def test_main_prints_report_and_diffs(tmp_path, capsys):
    pdf_path, web_path = tmp_path / "pdf.json", tmp_path / "web.json"
    pdf_path.write_text(json.dumps({"volume": PDF_TREE, "images": []}))
    web_path.write_text(json.dumps({"tree": WEB_TREE, "images": []}))

    main(["--pdf", str(pdf_path), "--web", str(web_path), "--diff"])

    out = capsys.readouterr().out
    assert "notes" in out
    assert "text mismatches" not in out  # Part/Notes titles agree once headings are stripped
