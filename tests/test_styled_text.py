import pytest

from shared.styled_text import StyledText, matches, style_of


def test_style_of_names_bold_italic_and_plain():
    assert style_of(bold=False, italic=False) == ""
    assert style_of(bold=True, italic=False) == "b"
    assert style_of(bold=False, italic=True) == "i"
    assert style_of(bold=True, italic=True) == "bi"


def test_from_runs_concatenates_and_records_each_styled_run():
    styled = StyledText.from_runs([("a new ", ""), ("building", "i"), (",", "")])

    assert styled.text == "a new building,"
    assert styled.emphasis == ((6, 14, "i"),)


def test_from_runs_merges_touching_runs_of_the_same_style():
    styled = StyledText.from_runs([("unsafe ", "i"), ("condition", "i")])

    assert styled.emphasis == ((0, 16, "i"),)


def test_from_runs_strips_outer_whitespace_and_shifts_the_ranges():
    styled = StyledText.from_runs([("  x ", ""), ("bold", "b"), ("  ", "")])

    assert styled.text == "x bold"
    assert styled.emphasis == ((2, 6, "b"),)


def test_from_runs_drops_a_styled_run_that_is_only_whitespace_at_the_edge():
    styled = StyledText.from_runs([("text", ""), ("   ", "i")])

    assert styled.text == "text"
    assert styled.emphasis == ()


def test_from_runs_of_nothing_is_empty():
    assert StyledText.from_runs([]) == StyledText("")


def test_join_puts_one_space_between_and_shifts_the_right_hand_ranges():
    left = StyledText("of any building", ((7, 15, "i"),))
    right = StyledText("that is", ())

    joined = left.join(StyledText("heritage buildings", ((0, 18, "i"),))).join(right)

    assert joined.text == "of any building heritage buildings that is"
    assert joined.emphasis == ((7, 15, "i"), (16, 34, "i"))


def test_join_with_an_empty_side_keeps_the_other_side_unchanged():
    styled = StyledText("word", ((0, 4, "b"),))

    assert StyledText("").join(styled) == styled
    assert styled.join(StyledText("")) == styled


def test_slice_keeps_only_the_tail_and_clips_ranges_that_cross_the_cut():
    styled = StyledText("1) This building", ((0, 2, "b"), (8, 16, "i")))

    tail = styled.slice(3)

    assert tail.text == "This building"
    assert tail.emphasis == ((5, 13, "i"),)


def test_slice_clips_a_range_that_starts_before_the_cut():
    assert StyledText("abcdef", ((1, 4, "i"),)).slice(2).emphasis == ((0, 2, "i"),)


def test_to_json_and_from_json_round_trip():
    styled = StyledText("a building", ((2, 10, "i"),))

    assert StyledText.from_json(styled.text, styled.emphasis_json()) == styled
    assert styled.emphasis_json() == [[2, 10, "i"]]


def test_from_json_treats_missing_emphasis_as_plain():
    assert StyledText.from_json("plain", None) == StyledText("plain")


def test_rejects_an_unknown_style():
    with pytest.raises(ValueError):
        StyledText("x", ((0, 1, "u"),))


def test_matches_ignores_every_whitespace_difference():
    assert matches(StyledText("see Note A- 1.1.1.1.(3) ."), StyledText("see Note A-1.1.1.1.(3)."))
    assert matches(StyledText("fire com partment"), StyledText("firecompartment"))


def test_matches_treats_curly_and_straight_quotes_as_the_same():
    assert matches(
        StyledText("“Fire Tests of Roof Coverings”"), StyledText('"Fire Tests of Roof Coverings"')
    )
    assert matches(StyledText("the owner’s ‘site’"), StyledText("the owner's 'site'"))
    assert not matches(StyledText('"quoted"'), StyledText("'quoted'"))


def test_matches_treats_every_dash_as_a_hyphen():
    """The PDF typesets – (en dash), — (em dash) and − (minus) where the
    web has a plain hyphen: an empty table cell's "—", a range
    "negligible – 0.01", a formula's "0.68 – (0.0005 Vr)"."""
    assert matches(StyledText("—"), StyledText("-"))
    assert matches(StyledText("negligible – 0.01"), StyledText("negligible - 0.01"))
    assert matches(StyledText("x − 1"), StyledText("x - 1"))
    assert matches(StyledText("non‑combustible"), StyledText("non-combustible"))


def test_a_dash_still_differs_from_other_punctuation_and_from_nothing():
    assert not matches(StyledText("—"), StyledText(""))
    assert not matches(StyledText("a – b"), StyledText("a , b"))


def test_matches_is_case_and_character_exact_otherwise():
    assert not matches(StyledText("Building"), StyledText("building"))
    assert not matches(StyledText("a building,"), StyledText("a building;"))


def test_matches_requires_the_same_italic_words():
    pdf = StyledText("a new building,", ((6, 14, "i"),))

    assert matches(pdf, StyledText("a  new building ,", ((7, 15, "i"),)))
    assert not matches(pdf, StyledText("a new building,"))


def test_matches_tells_bold_from_italic():
    assert not matches(StyledText("word", ((0, 4, "b"),)), StyledText("word", ((0, 4, "i"),)))
    assert not matches(StyledText("word", ((0, 4, "bi"),)), StyledText("word", ((0, 4, "i"),)))


def test_matches_ignores_the_styling_of_punctuation():
    italic_comma = StyledText("building,", ((0, 9, "i"),))
    plain_comma = StyledText("building,", ((0, 8, "i"),))

    assert matches(italic_comma, plain_comma)


def test_matches_two_empty_texts():
    assert matches(StyledText(""), StyledText("  "))


def test_between_keeps_a_middle_stretch_and_clips_its_ranges():
    styled = StyledText("ab cd ef", ((1, 4, "b"), (6, 8, "i")))
    assert styled.between(3, 5) == StyledText("cd", ((0, 1, "b"),))
    assert styled.between(6, 8) == StyledText("ef", ((0, 2, "i"),))


def test_matches_ignores_the_bullets_the_pdf_prints_before_list_items():
    """The PDF prints a bulleted list's "•" as text; the site renders the
    same list as <ul> items, whose bullets are not text - like a sentence's
    own "1)" marker, the bullet is the list's, not the item's content."""
    assert matches(
        StyledText("the following characteristics: • plasticity index, • moisture content"),
        StyledText("the following characteristics:plasticity index,moisture content"),
    )
    assert matches(StyledText("•"), StyledText(""))


def test_a_bullet_does_not_hide_a_real_difference():
    assert not matches(StyledText("• soil, • clay"), StyledText("soil, sand"))


def test_matches_reads_the_sites_typed_dashes_as_one_dash():
    """The site types an em dash as "---" and an en dash as "--" (Documents---the,
    Equipment and Systems -- Maximum), where the PDF typesets — and –."""
    assert matches(StyledText("—"), StyledText("---"))
    assert matches(StyledText("Code Documents—the"), StyledText("Code Documents---the"))
    assert matches(StyledText("Systems – Maximum"), StyledText("Systems -- Maximum"))


def test_separate_typed_dashes_stay_separate():
    assert matches(StyledText("— —"), StyledText("--- ---"))
    assert not matches(StyledText("—"), StyledText("--- ---"))
    assert not matches(StyledText("a-b"), StyledText("a--b--c"))


def test_matches_reads_every_dot_glyph_as_the_bullet_it_shares():
    """The PDF prints a unit's multiplication dot with the same "•" glyph as
    its bullets ("kWh/(m²•year)") where the site writes "·" - so, like the
    bullet, no dot glyph counts."""
    assert matches(StyledText("≤ 30 kWh/(m²•year)"), StyledText("≤ 30 kWh/(m²·year)"))
    assert matches(StyledText("W/m2·K"), StyledText("W/m2⋅K"))
