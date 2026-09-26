from mo_toc.parsing.body_segmenter import segment_article_body
from mo_toc.parsing.pdf_source import PageLine


def line(page_index, y0, x0, text):
    """Returns a (page_index, PageLine) pair, matching what tree_builder.py
    accumulates for an Article's body: a 0-based page index alongside the
    line, since PageLine itself carries no page number."""
    return (page_index, PageLine(bbox=(x0, y0, x0 + 200, y0 + 10), text=text, font="BookAntiqua"))


def styled_line(page_index, y0, x0, text, emphasis):
    pline = PageLine(
        bbox=(x0, y0, x0 + 200, y0 + 10), text=text, font="BookAntiqua", emphasis=emphasis
    )
    return (page_index, pline)


def test_marker_is_cut_from_the_emphasis_and_continuations_are_joined():
    body = [
        styled_line(5, 100, 50, "1) This building", ((0, 2, "b"), (8, 16, "i"))),
        styled_line(5, 112, 50, "is a heritage building.", ((5, 22, "i"),)),
    ]
    sentence = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)[0]
    assert sentence.content == "This building is a heritage building."
    assert sentence.emphasis == [(5, 13, "i"), (19, 36, "i")]


def test_clause_and_subclause_keep_their_own_emphasis():
    body = [
        line(5, 100, 50, "1) Applies to:"),
        styled_line(5, 112, 60, "a) a new building,", ((9, 17, "i"),)),
        styled_line(5, 124, 70, "i) an alteration,", ((6, 16, "i"),)),
    ]
    sentence = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)[0]
    clause = sentence.children[0]
    assert sentence.emphasis == []
    assert (clause.content, clause.emphasis) == ("a new building,", [(6, 14, "i")])
    subclause = clause.children[0]
    assert (subclause.content, subclause.emphasis) == ("an alteration,", [(3, 13, "i")])


def test_single_sentence_no_clauses():
    body = [line(5, 100, 50, "1) Fire protection shall conform to NFPA 303.")]
    sentences = segment_article_body(body, "B-2.16.2.1.", article_end_page=7)
    assert len(sentences) == 1
    s = sentences[0]
    assert s.type == "Sentence"
    assert s.identifier == "(1)"
    assert s.citation == "B-2.16.2.1.(1)"
    assert s.page == 6
    assert s.children == []


def test_sentence_with_clauses_and_subclauses():
    body = [
        line(5, 100, 50, "1) A design must satisfy all of the following:"),
        line(5, 112, 60, "a) structural adequacy,"),
        line(5, 124, 70, "i) under dead load, and"),
        line(5, 136, 70, "ii) under live load, and"),
        line(5, 148, 60, "b) fire safety."),
    ]
    sentences = segment_article_body(body, "B-1.1.1.1.", article_end_page=8)
    assert len(sentences) == 1
    clause_a, clause_b = sentences[0].children
    assert clause_a.citation == "B-1.1.1.1.(1)(a)"
    assert [c.citation for c in clause_a.children] == [
        "B-1.1.1.1.(1)(a)(i)",
        "B-1.1.1.1.(1)(a)(ii)",
    ]
    assert clause_b.citation == "B-1.1.1.1.(1)(b)"
    assert clause_b.children == []


def test_ambiguous_roman_letter_resolved_as_next_expected_clause():
    """A bare 'i)' right after 'h)' is clause (i) continuing a>b>c...>h>i, not a
    subclause of h) — confirmed real pattern in long alphabetic clause lists."""
    body = [
        line(5, 100, 50, "1) Many options:"),
        line(5, 112, 60, "h) option eight,"),
        line(5, 124, 60, "i) option nine."),
    ]
    sentences = segment_article_body(body, "B-3.1.1.1.", article_end_page=7)
    clause_h, clause_i = sentences[0].children
    assert clause_i.citation == "B-3.1.1.1.(1)(i)"
    assert clause_i.type == "Clause"


def test_ambiguous_roman_letter_priority_overrides_indent_threshold():
    """Priority (1) [next-expected-clause-letter] must win over priority (2)
    [x0-indent threshold] when they disagree. 'd)' is roman-shaped (ambiguous)
    and sits at x0=75 -- the same indent as this sentence's confirmed
    subclause 'iv)' -- while this sentence's confirmed clauses (a, b) sit at
    x0=60, giving a threshold of (60+75)/2=67.5. By indent alone (priority 2),
    x0=75 is not < 67.5, so 'd)' would be a Subclause. But 'd' is also the
    next expected clause letter after a, b, c, so priority (1) must resolve it
    as a Clause instead -- and as a direct child of the sentence, not nested
    under clause (c)."""
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) clause a"),
        line(5, 124, 75, "iv) subclause under a"),
        line(5, 136, 60, "b) clause b"),
        line(5, 148, 60, "c) clause c"),
        line(5, 160, 75, "d) clause d, deeply indented"),
    ]
    sentences = segment_article_body(body, "B-9.9.9.9.", article_end_page=7)
    clause_a, clause_b, clause_c, clause_d = sentences[0].children
    assert clause_d.type == "Clause"
    assert clause_d.citation == "B-9.9.9.9.(1)(d)"
    assert clause_d.bbox.x0 == 75
    assert clause_d.children == []
    assert clause_c.children == []


def test_preamble_before_first_sentence_marker_is_dropped():
    body = [
        line(5, 90, 50, "This introductory line has no marker."),
        line(5, 100, 50, "1) Actual sentence text."),
    ]
    sentences = segment_article_body(body, "B-1.1.1.1.", article_end_page=7)
    assert len(sentences) == 1


def test_empty_body_returns_no_sentences():
    assert segment_article_body([], "B-1.1.1.1.", article_end_page=7) == []


def test_last_sentence_end_page_falls_back_to_article_end_page():
    body = [line(5, 100, 50, "1) Only sentence.")]
    sentences = segment_article_body(body, "B-1.1.1.1.", article_end_page=9)
    assert sentences[0].end_page == 9


def test_last_sentence_end_page_clamped_when_article_end_page_precedes_it():
    # article_end_page is an inherited upper bound computed at the tree level
    # before this (last) sentence's own page was known (see Fix 1 in the
    # final-review report: _finalize_end_pages can hand a "last child"
    # article an end_page that's actually earlier than pages its own body
    # later lands on). end_page must never precede the sentence's own page.
    body = [line(5, 100, 50, "1) Only sentence, but article_end_page is stale.")]
    sentences = segment_article_body(body, "B-1.1.1.1.", article_end_page=3)
    assert sentences[0].page == 6
    assert sentences[0].end_page >= sentences[0].page


def test_clause_end_page_clamped_when_inherited_bound_precedes_it():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) clause a"),
    ]
    sentences = segment_article_body(body, "B-1.1.1.1.", article_end_page=3)
    clause_a = sentences[0].children[0]
    assert clause_a.page == 6
    assert clause_a.end_page >= clause_a.page


def test_ambiguous_roman_without_threshold_falls_back_to_proximity():
    """With only one confirmed clause and no confirmed subclause markers in
    the sentence, there aren't both samples needed to compute an indent
    threshold. An ambiguous roman-shaped marker that also isn't the next
    expected clause letter then falls back to comparing its indent against
    the previous clause's x0: indented more than 8pt past it reads as a
    Subclause of that clause."""
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) clause a"),
        line(5, 124, 80, "v) indented under a, not next-letter"),
    ]
    sentences = segment_article_body(body, "B-4.4.4.4.", article_end_page=7)
    clause_a = sentences[0].children[0]
    assert clause_a.citation == "B-4.4.4.4.(1)(a)"
    assert len(clause_a.children) == 1
    subclause = clause_a.children[0]
    assert subclause.type == "Subclause"
    assert subclause.identifier == "(v)"


def test_sentence_content_is_marker_stripped():
    body = [line(5, 100, 50, "1) Fire protection shall conform to NFPA 303.")]
    sentences = segment_article_body(body, "B-2.16.2.1.", article_end_page=7)
    assert sentences[0].content == "Fire protection shall conform to NFPA 303."
    assert sentences[0].title == ""


def test_clause_content_includes_wrapped_continuation_line():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(
            5,
            112,
            60,
            "a) except as permitted by the Fire Code, the installation, replacement, or",
        ),
        line(5, 124, 60, "alteration of materials or equipment regulated by this Code,"),
        line(5, 136, 60, "b) next clause,"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    clause_a, clause_b = sentences[0].children
    assert clause_a.content == (
        "except as permitted by the Fire Code, the installation, replacement, or "
        "alteration of materials or equipment regulated by this Code,"
    )
    assert clause_a.title == ""
    assert clause_b.content == "next clause,"


def test_clause_bbox_unions_continuation_line_on_same_page():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) first physical line"),
        line(5, 124, 65, "second physical line, wider"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    clause_a = sentences[0].children[0]
    assert clause_a.bbox.y0 == 112
    assert clause_a.bbox.y1 == 124 + 10  # line() gives each PageLine bbox height 10
    assert clause_a.bbox.x0 == 60


def test_continuation_line_on_a_later_page_extends_content_not_bbox():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) first physical line on page 6"),
        line(6, 40, 60, "continues on the next page"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=8)
    clause_a = sentences[0].children[0]
    assert clause_a.content == "first physical line on page 6 continues on the next page"
    assert clause_a.bbox.y0 == 112


def test_sentence_own_continuation_line_before_first_clause_marker():
    body = [
        line(5, 100, 50, "1) This sentence wraps onto"),
        line(5, 112, 50, "a second physical line before any clause starts,"),
        line(5, 124, 60, "a) then the first clause."),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    sentence = sentences[0]
    assert sentence.content == (
        "This sentence wraps onto a second physical line before any clause starts,"
    )
    assert sentence.children[0].content == "then the first clause."


def test_subclause_content_and_ownership_after_a_new_clause_resets():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) clause a"),
        line(5, 124, 75, "iv) subclause under a"),
        line(5, 136, 60, "b) clause b, no subclauses"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    clause_a, clause_b = sentences[0].children
    assert clause_a.children[0].content == "subclause under a"
    assert clause_b.content == "clause b, no subclauses"
    assert clause_b.children == []


def test_roman_i_after_non_h_clause_is_subclause_even_with_flat_indent():
    """Division A Article 1.3.3.2 (PDF page 15): every marker sits at the same
    x0 (~108.6pt), so the indent threshold is noise - 'i)' at 108.580 lands a
    hair left of it. 'i)' after 'b)' is not the next clause letter ('c') but
    is the next roman of (b)'s own i, ii, iii... sequence, so it opens a
    Subclause of (b); (c) and its own i..iv follow as normal."""
    body = [
        line(14, 119, 108.580, "1) Parts 3, 4, 5, and 6 apply to buildings"),
        line(14, 137, 108.580, "a) classified as post-disaster buildings,"),
        line(14, 155, 108.580, "b) used for major occupancies classified as"),
        line(14, 174, 108.580, "i) Group A, assembly occupancies,"),
        line(14, 192, 108.590, "ii) Group B, care occupancies, or"),
        line(14, 211, 108.600, "iii) Group F, Division 1, or"),
        line(14, 229, 108.610, "c) exceeding 600 m2 in building area"),
        line(14, 260, 108.595, "i) Group C, residential occupancies,"),
        line(14, 278, 108.595, "ii) Group D, business occupancies,"),
        line(14, 297, 108.595, "iii) Group E, mercantile occupancies, or"),
        line(14, 315, 108.595, "iv) Group F, Divisions 2 and 3."),
    ]
    sentences = segment_article_body(body, "A.1.3.3.2.", article_end_page=15)
    clauses = sentences[0].children
    assert [c.identifier for c in clauses] == ["(a)", "(b)", "(c)"]
    assert [s.identifier for s in clauses[1].children] == ["(i)", "(ii)", "(iii)"]
    assert [s.identifier for s in clauses[2].children] == ["(i)", "(ii)", "(iii)", "(iv)"]
    assert all(s.type == "Subclause" for c in clauses for s in c.children)


def test_roman_v_continuing_subclause_sequence_is_subclause_despite_threshold():
    """'v)' right after subclause 'iv)' continues the roman sequence even when
    the indent threshold would call it a clause."""
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 70, "a) clause a"),
        line(5, 124, 60, "i) one"),
        line(5, 136, 60, "ii) two"),
        line(5, 148, 60, "iii) three"),
        line(5, 160, 60, "iv) four"),
        line(5, 172, 60, "v) five"),
    ]
    sentences = segment_article_body(body, "B-5.5.5.5.", article_end_page=7)
    clause_a = sentences[0].children[0]
    assert [s.identifier for s in clause_a.children] == ["(i)", "(ii)", "(iii)", "(iv)", "(v)"]
