from dataclasses import dataclass, field

import pytest

from shared.numbering import Rule, assign_unified_numbers, normalize_identifier, number_images


@dataclass
class _StubNode:
    type: str
    identifier: str = ""
    citation: str = ""
    children: list["_StubNode"] = field(default_factory=list)
    unified_number: str = ""


@dataclass
class _StubImage:
    owner_citation: str
    decorative: bool = False
    unified_number: str = ""


RULES = {
    "Volume": Rule("root", "V"),
    "Division": Rule("root", fallback="FM"),
    "Appendix": Rule("root", "App"),
    "FrontMatter": Rule("fixed", "FM"),
    "Part": Rule("absolute"),
    "Article": Rule("absolute"),
    "Note": Rule("absolute"),
    "Sentence": Rule("child"),
    "Clause": Rule("suffix"),
    "Notes": Rule("literal", "Notes"),
    "Table": Rule("ordinal", "Tbl", scoped=True),
    "Row": Rule("ordinal", "Row"),
}
SCOPES = frozenset({"Article", "Note"})


def test_normalize_identifier_strips_trailing_dot_and_collapses_spaces():
    assert normalize_identifier("9.10.18.2.") == "9.10.18.2"
    assert normalize_identifier(" A-3.1.4.1.(1)  and (2) ") == "A-3.1.4.1.(1) and (2)"
    assert normalize_identifier("") == ""


def _numbered_volume_chain():
    clause = _StubNode("Clause", "(a)", "c")
    sentence = _StubNode("Sentence", "(2)", "s", [clause])
    article = _StubNode("Article", "9.10.18.2.", "a", [sentence])
    part = _StubNode("Part", "9", "p", [article])
    division = _StubNode("Division", "B", "d", [part])
    volume = _StubNode("Volume", "2", "v", [division])
    assign_unified_numbers([volume], RULES, SCOPES)
    return volume, division, part, article, sentence, clause


def test_official_numbers_build_the_key_and_volume_is_left_out():
    volume, division, part, *_ = _numbered_volume_chain()

    assert volume.unified_number == "V2"
    assert division.unified_number == "B"
    assert part.unified_number == "B.9"


def test_official_numbers_build_article_sentence_and_clause_keys():
    *_, article, sentence, clause = _numbered_volume_chain()

    assert article.unified_number == "B.9.10.18.2"
    assert sentence.unified_number == "B.9.10.18.2.(2)"
    assert clause.unified_number == "B.9.10.18.2.(2)(a)"


def test_missing_sibling_does_not_shift_later_keys():
    part10 = _StubNode("Part", "10", "p10")
    division = _StubNode("Division", "B", "d", [part10])  # Part 9 absent

    assign_unified_numbers([division], RULES)

    assert part10.unified_number == "B.10"


def test_literal_appends_fixed_segment_to_parent():
    notes = _StubNode("Notes", "1", "n")
    part = _StubNode("Part", "1", "p", [notes])
    division = _StubNode("Division", "A", "d", [part])

    assign_unified_numbers([division], RULES)

    assert notes.unified_number == "A.1.Notes"


def test_note_key_is_division_plus_official_note_number():
    note = _StubNode("Note", "A-1.1.1.1.(3)", "note")
    notes = _StubNode("Notes", "1", "n", [note])
    part = _StubNode("Part", "1", "p", [notes])
    division = _StubNode("Division", "A", "d", [part])

    assign_unified_numbers([division], RULES, SCOPES)

    assert note.unified_number == "A.A-1.1.1.1.(3)"


def test_scoped_table_ordinal_counts_within_owning_article_not_tree_parent():
    table_in_sentence = _StubNode("Table", "x", "t1")
    sentence = _StubNode("Sentence", "(1)", "s", [table_in_sentence])
    table_in_article = _StubNode("Table", "y", "t2")
    article = _StubNode("Article", "1.1.1.1", "a", [sentence, table_in_article])
    division = _StubNode("Division", "A", "d", [article])

    assign_unified_numbers([division], RULES, SCOPES)

    assert table_in_sentence.unified_number == "A.1.1.1.1.Tbl1"
    assert table_in_article.unified_number == "A.1.1.1.1.Tbl2"


def test_unscoped_ordinal_counts_under_parent():
    rows = [_StubNode("Row", "", f"r{i}") for i in range(2)]
    table = _StubNode("Table", "t", "t", rows)
    article = _StubNode("Article", "1.1.1.1", "a", [table])
    division = _StubNode("Division", "A", "d", [article])

    assign_unified_numbers([division], RULES, SCOPES)

    assert [r.unified_number for r in rows] == ["A.1.1.1.1.Tbl1.Row1", "A.1.1.1.1.Tbl1.Row2"]


def test_empty_identifier_uses_fallback_then_ordinal():
    article = _StubNode("Article", "", "a")
    preface = _StubNode("Division", "", "pre", [article])

    assign_unified_numbers([preface], RULES)

    assert preface.unified_number == "FM"
    assert article.unified_number == "FM.Article1"


def test_unmapped_type_is_an_ordinal_named_after_its_type():
    mystery = _StubNode("mystery", "", "m")
    division = _StubNode("Division", "A", "d", [mystery])

    assign_unified_numbers([division], RULES)

    assert mystery.unified_number == "A.mystery1"


def test_duplicate_key_gets_tilde_suffix():
    first = _StubNode("Part", "1", "p1")
    second = _StubNode("Part", "1", "p2")
    division = _StubNode("Division", "A", "d", [first, second])

    assign_unified_numbers([division], RULES)

    assert first.unified_number == "A.1"
    assert second.unified_number == "A.1~2"


def test_division_split_across_volumes_keeps_one_key():
    part1 = _StubNode("Part", "1", "p1")
    part9 = _StubNode("Part", "9", "p9")
    vol1 = _StubNode("Volume", "1", "v1", [_StubNode("Division", "B", "d1", [part1])])
    vol2 = _StubNode("Volume", "2", "v2", [_StubNode("Division", "B", "d2", [part9])])

    assign_unified_numbers([vol1, vol2], RULES)

    assert vol2.children[0].unified_number == "B"
    assert part9.unified_number == "B.9"


def test_fixed_and_root_prefix_rules():
    front = _StubNode("FrontMatter", "FrontMatter", "fm")
    appendix = _StubNode("Appendix", "D", "app")

    assign_unified_numbers([front, appendix], RULES)

    assert front.unified_number == "FM"
    assert appendix.unified_number == "AppD"


def test_unknown_rule_kind_raises():
    with pytest.raises(KeyError):
        assign_unified_numbers([_StubNode("X", "1", "x")], {"X": Rule("bogus")})


def test_returns_scope_key_per_citation():
    clause = _StubNode("Clause", "(a)", "clause-cit")
    sentence = _StubNode("Sentence", "(1)", "sent-cit", [clause])
    article = _StubNode("Article", "1.1.1.1", "art-cit", [sentence])
    front = _StubNode("FrontMatter", "", "fm-cit")
    division = _StubNode("Division", "A", "div-cit", [article])

    scope = assign_unified_numbers([front, division], RULES, SCOPES)

    assert scope["clause-cit"] == "A.1.1.1.1"
    assert scope["art-cit"] == "A.1.1.1.1"
    assert scope["fm-cit"] == "FM"


def test_duplicate_citation_keeps_the_first_nodes_scope():
    first = _StubNode("Article", "1.1.1.1", "dup")
    second = _StubNode("Article", "1.1.1.2", "dup")
    division = _StubNode("Division", "A", "d", [first, second])
    image = _StubImage("dup")

    scope = assign_unified_numbers([division], RULES, SCOPES)
    number_images([image], scope)

    assert scope["dup"] == "A.1.1.1.1"
    assert image.unified_number == "A.1.1.1.1.Fig1"


def test_empty_node_list_returns_empty_map():
    assert assign_unified_numbers([], RULES) == {}


def test_number_images_counts_per_scope_and_skips():
    images = [
        _StubImage("clause-cit"),
        _StubImage("clause-cit", decorative=True),
        _StubImage("art-cit"),
        _StubImage("unknown-cit"),
    ]
    scope = {"clause-cit": "A.1.1.1.1", "art-cit": "A.1.1.1.1"}

    number_images(images, scope, skip=lambda image: image.decorative)

    assert [i.unified_number for i in images] == ["A.1.1.1.1.Fig1", "", "A.1.1.1.1.Fig2", ""]


def test_number_images_without_skip_numbers_everything_resolvable():
    images = [_StubImage("a"), _StubImage("a")]

    number_images(images, {"a": "B.9.1.1.1"})

    assert [i.unified_number for i in images] == ["B.9.1.1.1.Fig1", "B.9.1.1.1.Fig2"]


def test_number_images_uses_the_given_label():
    images = [_StubImage("a"), _StubImage("a")]

    number_images(images, {"a": "B.9.15.3.4"}, label="Eq")

    assert [i.unified_number for i in images] == ["B.9.15.3.4.Eq1", "B.9.15.3.4.Eq2"]
