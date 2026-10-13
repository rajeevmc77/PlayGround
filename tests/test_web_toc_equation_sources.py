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
