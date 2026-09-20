import pytest

from mo_toc.parsing.heading_rules import classify_caption_line, classify_heading_line

BLACK = "Arial-Black"
BOLD = "Arial-BoldMT"
BODY = "BookAntiqua"


@pytest.mark.parametrize(
    "text,font,expected_type",
    [
        ("Division A", BLACK, "Division"),
        ("Notes to Part 3", BLACK, "NotesContainer"),
        ("Part 1", BLACK, "Part"),
        ("Section  1.1.   General", BLACK, "Section"),
        ("1.1.1.1. Application of this Code", BLACK, "Article"),
        ("1.1.1. Application of this Code", BLACK, "Subsection"),
        ("Appendix D", BLACK, "Appendix"),
        ("Section D-1 Fire Safety", BLACK, "AppendixPart"),
        ("D-1.1.1. Scope", BLACK, "AppendixArticle"),
        ("D-1.1. General", BLACK, "AppendixSection"),
        ("Fire and Sound Resistance Tables", BLACK, "TableGroup"),
        ("PROVINCE OF BRITISH COLUMBIA", BOLD, "BackMatter"),
    ],
)
def test_recognizes_real_headings(text, font, expected_type):
    result = classify_heading_line(text, font)
    assert result is not None
    ntype, _match = result
    assert ntype == expected_type


def test_rejects_citation_reference_in_body_font():
    result = classify_heading_line("as required in Subsection 3.1.3.1. of Division A", BODY)
    assert result is None


def test_rejects_heading_shaped_text_in_wrong_font():
    result = classify_heading_line("Division A", BOLD)
    assert result is None


def test_article_pattern_tolerates_missing_space_extraction_quirk():
    result = classify_heading_line("3.2.2.64.Group D, up to 2 Storeys", BLACK)
    assert result is not None
    assert result[0] == "Article"


def test_backmatter_marker_rejected_in_body_font():
    assert classify_heading_line("PROVINCE OF BRITISH COLUMBIA", BODY) is None


def test_recognizes_table_caption():
    m = classify_caption_line("Table 9.10.3.1.-A", "Arial-BoldMT")
    assert m is not None
    assert m.group(1) == "Table"


def test_recognizes_figure_caption():
    m = classify_caption_line("Figure A-3.2.3.14.(1)-C", "Arial-BoldMT")
    assert m is not None
    assert m.group(1) == "Figure"


def test_rejects_caption_in_black_font():
    assert classify_caption_line("Table 9.10.3.1.-A", "Arial-Black") is None


def test_rejects_caption_in_narrow_font():
    """A table's own header/data cells use ArialNarrow-Bold and can coincidentally
    repeat a real caption's identifier — must not be misread as a second caption."""
    assert classify_caption_line("Table 9.10.3.1.-A", "ArialNarrow-Bold") is None


def test_rank_orders_division_above_article():
    from mo_toc.parsing.heading_rules import RANK

    assert RANK["Division"] < RANK["Article"]


def test_article_types_includes_appendix_article():
    from mo_toc.parsing.heading_rules import ARTICLE_TYPES

    assert "Article" in ARTICLE_TYPES
    assert "AppendixArticle" in ARTICLE_TYPES
