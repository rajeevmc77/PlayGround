from mo_toc.parsing.body_segmenter import segment_article_body
from mo_toc.parsing.pdf_source import PageLine


def line(page_index, y0, x0, text):
    """Returns a (page_index, PageLine) pair, matching what tree_builder.py
    accumulates for an Article's body: a 0-based page index alongside the
    line, since PageLine itself carries no page number."""
    return (page_index, PageLine(bbox=(x0, y0, x0 + 200, y0 + 10), text=text, font="BookAntiqua"))


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
