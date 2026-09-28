"""extract_appendix builds an appendix's own structure - sections,
subsections, articles and their numbered paragraphs - which the site's
navigation tree leaves out (Appendix D stops at the appendix itself), so
the PDF's "D-1.1.1." articles and their sentences had nothing to meet."""

from web_toc.parsing.appendix_extractor import extract_appendix

APPENDIX_D = "nbc.divB.appendixD"
ARTICLE = f"{APPENDIX_D}.appsect1.subsect1.article1"


def _paragraph(n, text):
    return {"type": "paragraph", "id": f"{ARTICLE}.para{n}", "content": text}


CONTENT = {
    "id": APPENDIX_D,
    "type": "appendix",
    "letter": "D",
    "sections": [
        {
            "id": f"{APPENDIX_D}.appsect1",
            "type": "appendix_section",
            "title": "General",
            "paragraphs": [{"type": "paragraph", "id": f"{APPENDIX_D}.appsect1.para1"}],
            "subsections": [
                {
                    "id": f"{APPENDIX_D}.appsect1.subsect1",
                    "type": "appendix_subsection",
                    "title": "Introduction",
                    "articles": [
                        {
                            "id": ARTICLE,
                            "type": "appendix_article",
                            "title": "Scope",
                            "content": [
                                _paragraph(1, "1) This."),
                                _paragraph(2, "2) That."),
                                {"type": "table", "id": f"{ARTICLE}.table1"},
                            ],
                        },
                        {
                            "id": f"{APPENDIX_D}.appsect1.subsect1.article3",
                            "type": "appendix_article",
                            "title": "Applicability of Ratings",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "id": f"{APPENDIX_D}.appsect1.subsect1.article3.para1",
                                    "content": "The ratings apply.",
                                }
                            ],
                        },
                    ],
                }
            ],
        },
        {"id": f"{APPENDIX_D}.appsect2", "type": "appendix_section", "title": "Ratings"},
    ],
}


def _only_section():
    [(owner, section), _second] = extract_appendix(CONTENT, APPENDIX_D)
    return owner, section


def test_each_section_is_owned_by_the_appendix_and_numbered_like_the_pdf():
    owned = extract_appendix(CONTENT, APPENDIX_D)
    assert [(owner, s.type, s.identifier, s.heading, s.title) for owner, s in owned] == [
        (APPENDIX_D, "appendix_section", "D-1", "Section D-1", "General"),
        (APPENDIX_D, "appendix_section", "D-2", "Section D-2", "Ratings"),
    ]


def test_subsections_and_articles_take_their_numbers_from_their_ids():
    _owner, section = _only_section()
    subsection = section.children[0]
    assert (subsection.type, subsection.identifier, subsection.heading) == (
        "appendix_subsection",
        "D-1.1",
        "D-1.1.",
    )
    articles = subsection.children
    assert [(a.type, a.identifier, a.heading, a.title, a.citation) for a in articles] == [
        ("appendix_article", "D-1.1.1", "D-1.1.1.", "Scope", ARTICLE),
        (
            "appendix_article",
            "D-1.1.3",
            "D-1.1.3.",
            "Applicability of Ratings",
            f"{APPENDIX_D}.appsect1.subsect1.article3",
        ),
    ]


def test_an_articles_numbered_paragraphs_are_its_sentences():
    _owner, section = _only_section()
    scope = section.children[0].children[0]
    assert [(s.type, s.identifier, s.citation, s.content) for s in scope.children] == [
        ("Sentence", "(1)", f"{ARTICLE}.para1", "1) This."),
        ("Sentence", "(2)", f"{ARTICLE}.para2", "2) That."),
    ]


def test_an_unnumbered_paragraph_is_no_sentence():
    _owner, section = _only_section()
    assert section.children[0].children[1].children == []


def test_an_appendixs_sections_that_are_no_appendix_sections_are_left_out():
    # Real case: Appendix C's "sections" are note divisions - the PDF has no
    # numbered structure there to meet.
    content = {
        "id": "nbc.divB.appendixC",
        "type": "appendix",
        "letter": "C",
        "sections": [{"id": "nbc.divB.appendixC.notediv1", "type": "note_division"}],
    }
    assert extract_appendix(content, "nbc.divB.appendixC") == []


def test_content_that_is_no_appendix_has_no_structure():
    assert extract_appendix({"id": "nbc.divB.part3.sect1", "content": []}, "x") == []
    assert extract_appendix({"type": "appendix", "letter": "C"}, "x") == []


def _article_with(paragraph):
    content = {**CONTENT, "sections": [dict(CONTENT["sections"][0])]}
    subsection = dict(content["sections"][0]["subsections"][0])
    subsection["articles"] = [{"id": ARTICLE, "type": "appendix_article", "content": [paragraph]}]
    content["sections"][0]["subsections"] = [subsection]
    [(_owner, section)] = extract_appendix(content, APPENDIX_D)
    return section.children[0].children[0]


def test_a_sentences_lettered_list_items_are_its_clauses_cited_by_position():
    # The site renders them a), b), ... with no ids; "<para>.li2" is the
    # layout's name for the paragraph's second list item.
    paragraph = _paragraph(1, "1) Provided:[LIST:bulleted]")
    paragraph["lists"] = [{"type": "bulleted", "items": [{"content": "one,"}, {"content": "two."}]}]
    [sentence] = _article_with(paragraph).children
    assert [(c.type, c.identifier, c.citation, c.content) for c in sentence.children] == [
        ("Clause", "(a)", f"{ARTICLE}.para1.li1", "one,"),
        ("Clause", "(b)", f"{ARTICLE}.para1.li2", "two."),
    ]


def test_a_variable_list_is_no_clause_and_takes_no_list_position():
    # "where t = ..." lists render as a <dl>, not the lettered <ol>.
    paragraph = _paragraph(1, "1) Use:[LIST:variable][LIST:alphabetic]")
    paragraph["lists"] = [
        {"type": "variable", "items": [{"symbol": "t", "description": "thickness"}]},
        {"type": "alphabetic", "items": [{"content": "first,"}]},
    ]
    [sentence] = _article_with(paragraph).children
    assert [(c.identifier, c.citation) for c in sentence.children] == [
        ("(a)", f"{ARTICLE}.para1.li1")
    ]


def test_a_clauses_nested_list_items_are_its_subclauses_not_more_clauses():
    # The JSON flattens nested lists: a paragraph's `lists` holds its clause
    # list and then, in order, the list each "[LIST:...]" inside an item
    # stands for. The layout names a nested item by its path, "<para>.li2.li1".
    paragraph = _paragraph(4, "4) Provided:[LIST:bulleted]")
    paragraph["lists"] = [
        {
            "type": "bulleted",
            "items": [
                {"content": "the insulation is preformed,"},
                {"content": "the membrane is attached to[LIST:bulleted]"},
                {"content": "a channel is installed."},
            ],
        },
        {"type": "bulleted", "items": [{"content": "wood trusses, or"}, {"content": "joists."}]},
    ]
    [sentence] = _article_with(paragraph).children
    para = f"{ARTICLE}.para4"
    assert [(c.identifier, c.citation) for c in sentence.children] == [
        ("(a)", f"{para}.li1"),
        ("(b)", f"{para}.li2"),
        ("(c)", f"{para}.li3"),
    ]
    subclauses = sentence.children[1].children
    assert [(s.type, s.identifier, s.citation, s.content) for s in subclauses] == [
        ("Subclause", "(i)", f"{para}.li2.li1", "wood trusses, or"),
        ("Subclause", "(ii)", f"{para}.li2.li2", "joists."),
    ]


def test_each_nested_list_goes_to_the_item_whose_placeholder_comes_first():
    paragraph = _paragraph(1, "1) Either:[LIST:bulleted]")
    paragraph["lists"] = [
        {
            "type": "bulleted",
            "items": [{"content": "a[LIST:bulleted]"}, {"content": "b[LIST:bulleted]"}],
        },
        {"type": "bulleted", "items": [{"content": "a-one"}]},
        {"type": "bulleted", "items": [{"content": "b-one"}, {"content": "b-two"}]},
    ]
    [sentence] = _article_with(paragraph).children
    assert [[s.content for s in c.children] for c in sentence.children] == [
        ["a-one"],
        ["b-one", "b-two"],
    ]
