"""failure_reasons gives every failed text item and image a reason the
viewer can show; containers get none (their own ✗ comes from an item inside)."""

from comparison.reasons import failure_reasons


def _node(unified_number, type_="Sentence", content="", children=(), identifier="", **extra):
    return {
        "unified_number": unified_number,
        "type": type_,
        "identifier": identifier,
        "content": content,
        "children": list(children),
        **extra,
    }


def _reasons(pdf_tree, web_tree, statuses, counterparts=None, pdf_images=(), web_images=()):
    return failure_reasons(
        pdf_tree, list(pdf_images), web_tree, list(web_images), statuses, counterparts or {}
    )


def test_a_failed_sentence_gets_its_text_difference():
    pdf = _node("A", "Article", children=[_node("A.(1)", content="7 m apart.", identifier="(1)")])
    web = _node(
        "A", "Article", children=[_node("A.(1)", content="1) 9 m apart.", identifier="(1)")]
    )
    reasons = _reasons(pdf, web, {"A": False, "A.(1)": False})
    assert reasons["A.(1)"]["kind"] == "text"
    # The site's own "1)" marker is not the difference.
    assert reasons["A.(1)"]["edits"][0]["web"][1] == "9"
    assert "A" not in reasons


def test_passed_items_have_no_reason():
    pdf = _node("A", content="Same.")
    assert _reasons(pdf, _node("A", content="Same."), {"A": True}) == {}


def test_an_item_with_no_web_counterpart_says_so():
    pdf = _node(
        "T",
        "Table",
        children=[_node("T.Row9", "Row", children=[_node("T.Row9.Col1", "Cell", "x")])],
    )
    web = _node("T", "Table")
    statuses = {"T": False, "T.Row9": False, "T.Row9.Col1": False}
    reasons = _reasons(pdf, web, statuses, counterparts={"T.Row9": None, "T.Row9.Col1": None})
    assert reasons["T.Row9.Col1"] == {"kind": "no_web"}


def test_a_cell_is_compared_with_the_cell_it_was_paired_with():
    pdf = _node("T.Row2.Col1", "Cell", "b,")
    web = _node("root", "root", children=[_node("T.Row1.Col1", "Cell", "b")])
    reasons = _reasons(
        pdf, web, {"T.Row2.Col1": False}, counterparts={"T.Row2.Col1": "T.Row1.Col1"}
    )
    assert reasons["T.Row2.Col1"]["category"] == "Punctuation"


def test_a_leaf_whose_text_matches_failed_on_an_image_it_holds():
    pdf = _node("A.(1)", content="See figure.", citation="c1")
    reasons = _reasons(pdf, _node("A.(1)", content="See figure."), {"A.(1)": False})
    assert reasons["A.(1)"] == {"kind": "image_inside"}


def test_a_failed_image_is_missing_on_the_site_or_differs():
    images = [{"unified_number": "A.Fig1"}, {"unified_number": "A.Fig2"}]
    statuses = {"A": True, "A.Fig1": False, "A.Fig2": False}
    reasons = _reasons(
        _node("A", content="x"),
        _node("A", content="x"),
        statuses,
        pdf_images=images,
        web_images=[{"unified_number": "A.Fig1"}],
    )
    assert reasons["A.Fig1"] == {"kind": "image_differs"}
    assert reasons["A.Fig2"] == {"kind": "no_web_image"}


def test_without_a_web_tree_every_failed_item_has_no_web_counterpart():
    assert _reasons(_node("A", content="x"), None, {"A": False}) == {"A": {"kind": "no_web"}}


def test_a_failed_image_is_judged_against_its_counterpart():
    images = [{"unified_number": "A.Fig1"}]
    reasons = _reasons(
        _node("A", content="x"),
        _node("A", content="x"),
        {"A": True, "A.Fig1": False},
        counterparts={"A.Fig1": "A.Eq1"},
        pdf_images=images,
        web_images=[{"unified_number": "A.Eq1"}],
    )
    assert reasons["A.Fig1"] == {"kind": "image_differs"}
