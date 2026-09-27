import pytest

from mo_toc.parsing.heading_rules import (
    classify_caption_line,
    classify_heading_line,
    font_family,
    is_table_notes_heading,
)

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


# Some real captions are set in the plain body font, not bold (e.g. "Table
# 9.8.4.2." on page 746, in ArialMT). They are told apart from a body-text
# reference by being alone on their line and centred on the page.
def test_recognizes_a_plain_font_caption_centred_alone_on_its_line():
    m = classify_caption_line("Table 9.8.4.2.", "ArialMT", centred=True)
    assert m is not None
    assert m.group(2) == "9.8.4.2."


@pytest.mark.parametrize(
    "text", ["Table 9.36.6.3.-B", "Table  A-9.11.1.4.-D", "Table D-2.6.1.-B", "Figure 4.1.7.13.-A"]
)
def test_recognizes_plain_font_captions_of_every_identifier_shape(text):
    assert classify_caption_line(text, "BookAntiqua", centred=True) is not None


def test_rejects_a_plain_font_caption_that_is_not_centred():
    assert classify_caption_line("Table 1.3.1.2.", "BookAntiqua") is None


def test_rejects_a_centred_plain_font_line_that_goes_on_past_the_identifier():
    assert classify_caption_line("Table 9.8.4.2. lists the runs", "ArialMT", centred=True) is None


def test_rejects_a_centred_caption_in_narrow_font():
    assert classify_caption_line("Table 5.9.1.1.", "ArialNarrow", centred=True) is None


def test_rank_orders_division_above_article():
    from mo_toc.parsing.heading_rules import RANK

    assert RANK["Division"] < RANK["Article"]


def test_article_types_includes_appendix_article():
    from mo_toc.parsing.heading_rules import ARTICLE_TYPES

    assert "Article" in ARTICLE_TYPES
    assert "AppendixArticle" in ARTICLE_TYPES


@pytest.mark.parametrize(
    "text",
    [
        "Notes to Table 3.1.13.2.:",
        "Note to Figure4.1.7.4.:",
        "Notes to Table A-9.11.1.4.-A:",
        "Notes to Figure A-1.1.3.1.(4):",
    ],
)
def test_recognizes_a_table_or_figure_notes_heading(text):
    assert is_table_notes_heading(text)


@pytest.mark.parametrize(
    "text",
    ["Notes to Part 1", "Notes to Table", "See the Notes to Table 3.1.13.2. for details."],
)
def test_rejects_lines_that_do_not_head_a_table_or_figure_notes_block(text):
    assert not is_table_notes_heading(text)


@pytest.mark.parametrize(
    ("font", "family"),
    [
        ("ArialMT", "Arial"),
        ("Arial-ItalicMT/ArialMT", "Arial"),
        ("Arial-BoldMT", "Arial"),
        ("ArialNarrow-Bold", "ArialNarrow"),
        ("TimesNewRomanPSMT", "TimesNewRoman"),
        ("TimesNewRomanPS-BoldMT", "TimesNewRoman"),
        ("BookAntiqua/BookAntiqua-Italic", "BookAntiqua"),
        ("", ""),
    ],
)
def test_font_family_drops_weight_style_and_foundry_suffixes(font, family):
    assert font_family(font) == family
