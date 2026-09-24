from web_toc.domain.models import WebNode
from web_toc.parsing.body_extractor import attach_body, extract_body


def _real_shaped_sentence(sentence_id="nbc.divA.part1.sect1.subsect1.art1.sent1"):
    return {
        "id": sentence_id,
        "type": "sentence",
        "number": 1,
        "text": "This Code applies to any one or more of the following:",
        "clauses": [
            {
                "id": f"{sentence_id}.clause1",
                "type": "clause",
                "letter": "a",
                "text": "the design and construction of a new building,",
                "subclauses": [
                    {
                        "id": f"{sentence_id}.clause1.subclause1",
                        "type": "subclause",
                        "number": 1,
                        "text": "that remain after a demolition,",
                    },
                    {
                        "id": f"{sentence_id}.clause1.subclause2",
                        "type": "subclause",
                        "number": 2,
                        "text": "that are new construction,",
                    },
                ],
            },
            {
                "id": f"{sentence_id}.clause2",
                "type": "clause",
                "letter": "b",
                "text": "the demolition of a building.",
            },
        ],
    }


def test_sentence_matches_deepest_ancestor_citation():
    citations = {"nbc.divA.part1.sect1", "nbc.divA.part1.sect1.subsect1.art1"}
    content = {
        "id": "nbc.divA.part1.sect1",
        "subsections": [
            {
                "articles": [
                    {"content": [_real_shaped_sentence("nbc.divA.part1.sect1.subsect1.art1.sent1")]}
                ]
            }
        ],
    }
    owned = extract_body(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert len(owned) == 1
    owner, sentence_node = owned[0]
    assert owner == "nbc.divA.part1.sect1.subsect1.art1"
    assert sentence_node.type == "Sentence"
    assert sentence_node.identifier == "(1)"
    assert sentence_node.content == "This Code applies to any one or more of the following:"


def test_sentence_falls_back_to_enclosing_node_when_no_deeper_match():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [_real_shaped_sentence("nbc.divA.part1.sect1.subsect9.art9.sent1")]}
    owned = extract_body(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert owned[0][0] == "nbc.divA.part1.sect1"


def test_sentence_builds_nested_clause_and_subclause_children():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [_real_shaped_sentence("nbc.divA.part1.sect1.sent1")]}
    _, sentence_node = extract_body(content, citations, "nbc.divA.part1.sect1")[0]

    assert len(sentence_node.children) == 2
    clause_a, clause_b = sentence_node.children
    assert clause_a.type == "Clause"
    assert clause_a.identifier == "(a)"
    assert clause_a.content == "the design and construction of a new building,"
    assert clause_b.identifier == "(b)"
    assert clause_b.children == []

    assert len(clause_a.children) == 2
    subclause_i, subclause_ii = clause_a.children
    assert subclause_i.type == "Subclause"
    assert subclause_i.identifier == "(i)"
    assert subclause_i.content == "that remain after a demolition,"
    assert subclause_ii.identifier == "(ii)"


def test_subclause_number_converts_to_lowercase_roman_numerals():
    citations = {"nbc.divA.part1.sect1"}
    sentence = _real_shaped_sentence("nbc.divA.part1.sect1.sent1")
    sentence["clauses"][0]["subclauses"] = [
        {"id": f"nbc.divA.part1.sect1.sent1.clause1.subclause{n}", "type": "subclause", "number": n}
        for n in range(1, 6)
    ]
    content = {"content": [sentence]}
    _, sentence_node = extract_body(content, citations, "nbc.divA.part1.sect1")[0]
    identifiers = [sc.identifier for sc in sentence_node.children[0].children]
    assert identifiers == ["(i)", "(ii)", "(iii)", "(iv)", "(v)"]


def test_sentence_citation_is_its_own_id():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [_real_shaped_sentence("nbc.divA.part1.sect1.sent1")]}
    _, sentence_node = extract_body(content, citations, "nbc.divA.part1.sect1")[0]
    assert sentence_node.citation == "nbc.divA.part1.sect1.sent1"


def test_no_sentences_returns_empty_list():
    content = {"id": "nbc.divA.part1.sect1", "subsections": []}
    assert extract_body(content, {"nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1") == []


def test_sentence_without_id_is_skipped_not_crashed():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            {"type": "sentence", "number": 1, "text": "Malformed"},
            _real_shaped_sentence("nbc.divA.part1.sect1.sent1"),
        ]
    }
    owned = extract_body(content, citations, "nbc.divA.part1.sect1")
    assert len(owned) == 1
    assert owned[0][1].citation == "nbc.divA.part1.sect1.sent1"


def test_clause_without_id_is_skipped_not_crashed():
    citations = {"nbc.divA.part1.sect1"}
    sentence = _real_shaped_sentence("nbc.divA.part1.sect1.sent1")
    sentence["clauses"].append({"type": "clause", "letter": "z", "text": "Malformed"})
    content = {"content": [sentence]}
    _, sentence_node = extract_body(content, citations, "nbc.divA.part1.sect1")[0]
    assert [c.identifier for c in sentence_node.children] == ["(a)", "(b)"]


def test_sentence_does_not_descend_into_its_own_clauses_during_the_walk():
    # A malformed/duplicate top-level "clause" sitting alongside a sentence
    # (not nested inside it) must not be picked up by extract_body at all -
    # only "sentence" nodes are ever extracted directly.
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            _real_shaped_sentence("nbc.divA.part1.sect1.sent1"),
            {"id": "stray.clause1", "type": "clause", "letter": "z", "text": "Stray"},
        ]
    }
    owned = extract_body(content, citations, "nbc.divA.part1.sect1")
    assert len(owned) == 1


def test_multiple_sentences_in_one_content_json_are_all_extracted():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            _real_shaped_sentence("nbc.divA.part1.sect1.sentA"),
            _real_shaped_sentence("nbc.divA.part1.sect1.sentB"),
        ]
    }
    owned = extract_body(content, citations, "nbc.divA.part1.sect1")
    assert {node.citation for _, node in owned} == {
        "nbc.divA.part1.sect1.sentA",
        "nbc.divA.part1.sect1.sentB",
    }


def test_attach_body_appends_each_sentence_under_its_owner_node():
    owner = WebNode(
        type="article", identifier="1", citation="nbc.divA.part1.sect1.art1", title="", path=""
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[owner])
    sentence_node = WebNode(
        type="Sentence",
        identifier="(1)",
        citation="nbc.divA.part1.sect1.art1.sent1",
        title="",
        path="",
    )

    attach_body(root, [("nbc.divA.part1.sect1.art1", sentence_node)])

    assert owner.children == [sentence_node]
