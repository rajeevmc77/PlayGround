from web_toc.parsing.numbering_config import (
    WEB_TOC_IDENTIFIER_TYPES,
    WEB_TOC_SUFFIX_TYPES,
    WEB_TOC_TYPE_MARKERS,
)

CANONICAL_LEVELS = ["volume", "division", "part", "section", "subsection", "article"]

MARKER_TYPES = {
    "part_appendix": "App",
    "division_appendix": "App",
    "index": "Idx",
    "conversions": "Conv",
    "spectables": "Spec",
}


def test_canonical_document_levels_map_to_none():
    for level in CANONICAL_LEVELS:
        assert WEB_TOC_TYPE_MARKERS[level] is None


def test_non_level_types_map_to_short_markers():
    for node_type, marker in MARKER_TYPES.items():
        assert WEB_TOC_TYPE_MARKERS[node_type] == marker


def test_table_has_exactly_the_expected_keys():
    assert set(WEB_TOC_TYPE_MARKERS) == set(CANONICAL_LEVELS) | set(MARKER_TYPES)


def test_synthetic_root_type_is_not_in_the_table():
    assert "root" not in WEB_TOC_TYPE_MARKERS


def test_division_is_the_only_identifier_type():
    assert WEB_TOC_IDENTIFIER_TYPES == frozenset({"division"})


def test_no_suffix_types_yet_web_toc_has_no_sentence_level_nodes():
    assert WEB_TOC_SUFFIX_TYPES == frozenset()
