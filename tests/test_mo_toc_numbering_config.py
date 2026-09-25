from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from shared.numbering import Rule


def test_official_number_levels_are_absolute():
    for level in (
        "Part",
        "Section",
        "Subsection",
        "Article",
        "Note",
        "AppendixPart",
        "AppendixSection",
        "AppendixArticle",
    ):
        assert MO_TOC_RULES[level] == Rule("absolute")


def test_chain_restarting_levels():
    assert MO_TOC_RULES["Volume"] == Rule("fixed", "V1")
    assert MO_TOC_RULES["FrontMatter"] == Rule("fixed", "FM")
    assert MO_TOC_RULES["BackMatter"] == Rule("fixed", "BM")
    assert MO_TOC_RULES["Division"] == Rule("root")
    assert MO_TOC_RULES["Appendix"] == Rule("root", "App")


def test_body_and_table_levels():
    assert MO_TOC_RULES["Sentence"] == Rule("child")
    assert MO_TOC_RULES["Clause"] == Rule("suffix")
    assert MO_TOC_RULES["Subclause"] == Rule("suffix")
    assert MO_TOC_RULES["NotesContainer"] == Rule("literal", "Notes")
    assert MO_TOC_RULES["TableGroup"] == Rule("ordinal", "Spec")
    assert MO_TOC_RULES["Table"] == Rule("ordinal", "Tbl", scoped=True)
    assert MO_TOC_RULES["Row"] == Rule("ordinal", "Row")
    assert MO_TOC_RULES["Cell"] == Rule("ordinal", "Col")


def test_rule_table_covers_exactly_the_expected_node_types():
    assert set(MO_TOC_RULES) == {
        "Volume",
        "FrontMatter",
        "BackMatter",
        "Division",
        "Appendix",
        "Part",
        "Section",
        "Subsection",
        "Article",
        "Note",
        "AppendixPart",
        "AppendixSection",
        "AppendixArticle",
        "Sentence",
        "Clause",
        "Subclause",
        "NotesContainer",
        "TableGroup",
        "Table",
        "Row",
        "Cell",
    }


def test_scope_types_are_exactly_the_expected_set():
    assert MO_TOC_SCOPE_TYPES == frozenset(
        {"Part", "Section", "Subsection", "Article", "NotesContainer", "Note", "TableGroup"}
    )


def test_appendix_sub_levels_are_not_table_scopes():
    # the web keeps Appendix C/D tables directly under the appendix
    assert {"AppendixPart", "AppendixSection", "AppendixArticle"}.isdisjoint(MO_TOC_SCOPE_TYPES)
    assert {"Article", "Note", "NotesContainer", "TableGroup"} <= MO_TOC_SCOPE_TYPES
