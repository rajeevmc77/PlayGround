from shared.numbering import Rule
from web_toc.parsing.numbering_config import WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES


def test_official_number_levels_are_absolute():
    for level in ("part", "section", "subsection", "article", "Note"):
        assert WEB_TOC_RULES[level] == Rule("absolute")


def test_chain_restarting_levels():
    assert WEB_TOC_RULES["volume"] == Rule("root", "V")
    assert WEB_TOC_RULES["division"] == Rule("root", fallback="FM")
    assert WEB_TOC_RULES["division_appendix"] == Rule("root", "App")


def test_body_levels():
    assert WEB_TOC_RULES["Sentence"] == Rule("child")
    assert WEB_TOC_RULES["Clause"] == Rule("suffix")
    assert WEB_TOC_RULES["Subclause"] == Rule("suffix")
    assert WEB_TOC_RULES["part_appendix"] == Rule("literal", "Notes")


def test_notes_and_table_levels():
    assert WEB_TOC_RULES["spectables"] == Rule("ordinal", "Spec")
    assert WEB_TOC_RULES["index"] == Rule("ordinal", "Idx")
    assert WEB_TOC_RULES["conversions"] == Rule("ordinal", "Conv")
    assert WEB_TOC_RULES["Table"] == Rule("ordinal", "Tbl", scoped=True)
    assert WEB_TOC_RULES["Row"] == Rule("ordinal", "Row")
    assert WEB_TOC_RULES["Cell"] == Rule("ordinal", "Col")


def test_rule_table_covers_exactly_the_expected_node_types():
    assert set(WEB_TOC_RULES) == {
        "volume",
        "division",
        "division_appendix",
        "part",
        "section",
        "subsection",
        "article",
        "Note",
        "Sentence",
        "Clause",
        "Subclause",
        "part_appendix",
        "spectables",
        "index",
        "conversions",
        "Table",
        "Row",
        "Cell",
    }


def test_synthetic_root_is_never_numbered():
    assert "root" not in WEB_TOC_RULES


def test_scope_types_are_exactly_the_expected_set():
    assert WEB_TOC_SCOPE_TYPES == frozenset(
        {
            "part",
            "section",
            "subsection",
            "article",
            "part_appendix",
            "Note",
            "spectables",
            "index",
            "conversions",
        }
    )


def test_scope_types():
    assert {"article", "Note", "part_appendix", "spectables"} <= WEB_TOC_SCOPE_TYPES
