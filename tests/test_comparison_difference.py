"""describe_difference says why a PDF item's text and its web counterpart's
don't match: which stretches differ (with a little context either side),
what kind of difference each one is, or which words' bold/italic differ."""

from comparison.difference import describe_difference
from shared.styled_text import StyledText


def _describe(pdf, web, pdf_emphasis=(), web_emphasis=()):
    return describe_difference(StyledText(pdf, pdf_emphasis), StyledText(web, web_emphasis))


def test_matching_text_and_emphasis_has_no_difference():
    assert _describe("Plain words.", "Plain  words.") is None


def test_a_missing_letter_suffix_is_shown_with_its_context():
    reason = _describe(
        "the limiting distance in Table 3.2.3.1.-B permits an area",
        "the limiting distance in Table 3.2.3.1. permits an area",
    )
    assert reason["kind"] == "text"
    [edit] = reason["edits"]
    assert edit["pdf"][1] == "-B"
    assert edit["web"][1] == ""
    assert edit["pdf"][0].endswith("Table 3.2.3.1.")
    assert edit["pdf"][2].startswith(" permits")


def test_a_repeated_reference_word_is_reference_wording():
    reason = _describe(
        "Articles 3.1.2.3. to 3.1.2.5. apply", "Articles 3.1.2.3. to Article 3.1.2.5. apply"
    )
    assert reason["category"] == "Reference wording"
    assert reason["edits"][0]["web"][1] == "Article"


def test_an_added_issuing_body_is_a_standard_designation():
    reason = _describe("conforming to CAN/ULC-S138, a", "conforming to ULC CAN/ULC-S138, a")
    assert reason["category"] == "Standard designation"


def test_a_comma_dropped_is_punctuation():
    assert _describe("reserved,", "reserved")["category"] == "Punctuation"


def test_a_change_of_letter_case_is_letter_case():
    reason = _describe("Building Acoustics", "Building acoustics")
    assert reason["category"] == "Letter case"


def test_a_note_prefix_added_is_note_link_text():
    assert _describe("A-4.3.4.2.(1)", "Note A-4.3.4.2.(1)")["category"] == "Note link text"


def test_other_changes_are_wording_and_several_kinds_are_mixed():
    assert _describe("shall be 7 m", "shall be 9 m")["category"] == "Wording"
    reason = _describe(
        "Articles 1.1.1. to 1.1.2., and x", "Articles 1.1.1. to Article 1.1.2. and y"
    )
    assert reason["category"] == "Mixed"


def test_at_most_three_edits_are_listed_with_the_total():
    reason = _describe("a1 b2 c3 d4 e5", "a9 b8 c7 d6 e0")
    assert len(reason["edits"]) == 3
    assert reason["edit_count"] == 5


def test_same_words_with_other_bold_name_the_words_and_their_styles():
    reason = _describe("9.3.1.1. General", "9.3.1.1. General", pdf_emphasis=((0, 16, "b"),))
    assert reason["kind"] == "emphasis"
    [edit] = reason["edits"]
    assert edit["pdf"][1] == "9.3.1.1. General"
    assert (edit["pdf_style"], edit["web_style"]) == ("bold", "plain")


def test_an_italic_word_only_on_the_site_is_named():
    reason = _describe(
        "Storey supporting roof", "Storey supporting roof", web_emphasis=((0, 6, "i"),)
    )
    [edit] = reason["edits"]
    assert (edit["pdf"][1], edit["pdf_style"], edit["web_style"]) == ("Storey", "plain", "italic")


def test_an_empty_side_is_its_own_kind():
    assert _describe("", "Single storey building configuration")["kind"] == "pdf_empty"
    assert _describe("Concrete, mm", "")["kind"] == "web_empty"


def test_a_change_after_a_bullet_is_mapped_back_to_the_original_text():
    reason = _describe("contains: • quick clay, • moss", "contains:quick clay,gravel")
    [edit] = reason["edits"]
    assert edit["pdf"][1] == "moss"
    assert edit["web"][1] == "gravel"
    assert edit["pdf"][0].endswith("clay, • ")


def test_a_change_after_a_typed_dash_is_mapped_back_to_the_original_text():
    reason = _describe("Code Documents—the moss", "Code Documents---the gravel")
    [edit] = reason["edits"]
    assert edit["pdf"][1] == "moss"
    assert edit["web"][1] == "gravel"
    assert edit["web"][0].endswith("Documents---the ")
