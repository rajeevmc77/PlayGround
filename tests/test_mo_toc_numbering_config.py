from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)

CANONICAL_LEVELS = [
    "Volume",
    "Division",
    "Part",
    "Section",
    "Subsection",
    "Article",
    "Sentence",
    "Clause",
    "Subclause",
]

MARKER_TYPES = {
    "FrontMatter": "FM",
    "BackMatter": "BM",
    "Appendix": "App",
    "AppendixPart": "AppPt",
    "AppendixSection": "AppSec",
    "AppendixArticle": "AppArt",
    "NotesContainer": "Notes",
    "Note": "Note",
    "TableGroup": "Tbl",
}


def test_canonical_document_levels_map_to_none():
    for level in CANONICAL_LEVELS:
        assert MO_TOC_TYPE_MARKERS[level] is None


def test_non_level_types_map_to_short_markers():
    for node_type, marker in MARKER_TYPES.items():
        assert MO_TOC_TYPE_MARKERS[node_type] == marker


def test_table_has_exactly_the_expected_keys():
    assert set(MO_TOC_TYPE_MARKERS) == set(CANONICAL_LEVELS) | set(MARKER_TYPES)


def test_division_and_sentence_are_the_identifier_types():
    assert MO_TOC_IDENTIFIER_TYPES == frozenset({"Division", "Sentence"})


def test_clause_and_subclause_are_the_suffix_types():
    assert MO_TOC_SUFFIX_TYPES == frozenset({"Clause", "Subclause"})
