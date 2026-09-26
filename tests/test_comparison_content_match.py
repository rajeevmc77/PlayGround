"""content_matches: a PDF leaf and its web counterpart match when their text
is identical apart from whitespace and every letter/digit carries the same
bold/italic - the only formatting the comparison looks at."""

from comparison.content_match import content_matches


def _node(content, emphasis=None, type_="Cell", identifier=""):
    node = {"type": type_, "identifier": identifier, "content": content}
    if emphasis is not None:
        node["emphasis"] = emphasis
    return node


def test_text_differing_only_in_whitespace_matches():
    pdf = _node("a fire- resistance rating per Note A- 1.1.1.1.(3) .")
    web = _node("a fire-resistance rating per Note A-1.1.1.1.(3).")
    assert content_matches(pdf, web)


def test_any_other_text_difference_fails_even_a_single_character():
    assert not content_matches(_node("Class A roofing"), _node("Class B roofing"))
    assert not content_matches(_node("“Fire Tests”"), _node('"Fire Tests"'))


def test_the_same_italic_words_match_and_a_missing_italic_fails():
    pdf = _node("a new building,", [[6, 14, "i"]])
    assert content_matches(pdf, _node("a new building ,", [[6, 14, "i"]]))
    assert not content_matches(pdf, _node("a new building,"))


def test_bold_is_not_italic():
    assert not content_matches(_node("Total", [[0, 5, "b"]]), _node("Total", [[0, 5, "i"]]))


def test_missing_emphasis_means_plain_text_on_either_side():
    assert content_matches(_node("plain"), _node("plain", []))


def test_the_webs_own_marker_is_dropped_from_a_sentence_clause_or_subclause():
    pdf = _node("This Code applies", type_="Sentence", identifier="(1)")
    web = _node("1) This Code applies", [[0, 2, "b"]], type_="Sentence", identifier="(1)")
    assert content_matches(pdf, web)

    pdf_clause = _node("a new building,", [[6, 14, "i"]], "Clause", "(a)")
    web_clause = _node("(a) a new building,", [[10, 18, "i"]], "Clause", "(a)")
    assert content_matches(pdf_clause, web_clause)


def test_a_leading_token_that_is_not_the_nodes_own_marker_is_kept():
    pdf = _node("the design", type_="Clause", identifier="(a)")
    web = _node("b) the design", type_="Clause", identifier="(a)")
    assert not content_matches(pdf, web)


def test_a_cell_keeps_leading_text_that_looks_like_a_marker():
    assert not content_matches(_node("Heading"), _node("1) Heading", identifier="(1)"))


def test_empty_on_both_sides_matches_but_one_sided_content_does_not():
    assert content_matches(_node(""), _node(""))
    assert not content_matches(_node("some real content"), _node(""))
