from web_toc.parsing.equation_sources import equation_sources_in_content


def test_finds_a_top_level_equation_node():
    content = {"id": "s1", "content": [{"type": "sentence", "id": "es1", "latex": "W=w"}]}
    sources = equation_sources_in_content(content)
    assert sources["es1"].latex == "W=w"
    assert sources["es1"].mathml is None


def test_finds_an_arbitrarily_nested_equation_node():
    # A formula can sit inside a sentence's clauses, or inside a table cell -
    # this must not assume a fixed shape.
    content = {
        "id": "s1",
        "content": [
            {
                "type": "table",
                "id": "t1",
                "rows": [{"cells": [{"id": "eg1", "latex": "l_c", "mathml": "<math/>"}]}],
            }
        ],
    }
    sources = equation_sources_in_content(content)
    assert sources["eg1"].latex == "l_c"
    assert sources["eg1"].mathml == "<math/>"


def test_a_node_with_an_empty_id_is_excluded():
    content = {"id": "s1", "content": [{"type": "sentence", "id": "", "latex": "x"}]}
    assert equation_sources_in_content(content) == {}


def test_no_equations_returns_an_empty_dict():
    assert equation_sources_in_content({"id": "s1", "content": []}) == {}


def test_a_node_with_no_latex_is_not_a_source():
    content = {"id": "s1", "content": [{"type": "sentence", "id": "es1", "text": "plain text"}]}
    assert equation_sources_in_content(content) == {}


def test_an_equation_with_only_plain_text_is_typeset_from_that_text():
    # AppC's ex000108q1/q2 carry neither latex nor mathml, yet the site
    # typesets them with MathJax from their plainText as TeX ("S_{s}" comes
    # out subscripted); without a source their PNG was never written while
    # the saved page and bcbc_web.json still pointed at it.
    node = {"id": "ex1", "type": "display", "plainText": "S_{s} = smooth normalized SL + bZ"}
    sources = equation_sources_in_content({"id": "c", "equations": [node]})
    assert sources["ex1"].latex == "S_{s} = smooth normalized SL + bZ"
    assert sources["ex1"].mathml is None


def test_latex_wins_over_plain_text_when_both_are_present():
    node = {"id": "e1", "latex": "a\\times b", "plainText": "a×b", "mathml": "<math/>"}
    assert equation_sources_in_content({"equations": [node]})["e1"].latex == "a\\times b"


def test_a_plain_text_only_node_with_an_empty_id_is_excluded():
    node = {"id": "", "type": "display", "plainText": "36.74 W/K – 35.32 W/K = 1.42 W/K"}
    assert equation_sources_in_content({"equations": [node]}) == {}
