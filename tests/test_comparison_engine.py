"""compare_trees rolls a pass/fail status up the PDF tree: a node passes
only if its own text matches, every image it owns matches, and every child
(recursively) passes. A unified_number missing on the web side always fails.
text_matches/images_match are injected so these tests stay pure and fast -
see test_comparison_text_similarity.py / test_comparison_image_similarity.py
for the real implementations these fakes stand in for."""

from comparison.engine import compare_trees


def _node(unified_number, citation, content="", children=None):
    return {
        "unified_number": unified_number,
        "citation": citation,
        "content": content,
        "children": children or [],
    }


def _image(unified_number, owner_citation):
    return {"unified_number": unified_number, "owner_citation": owner_citation}


ALWAYS_MATCH = lambda a, b: True  # noqa: E731
NEVER_MATCH = lambda a, b: False  # noqa: E731


def test_matching_leaf_rolls_up_to_a_passing_parent():
    pdf_tree = _node("P1", "part1", "same text", children=[_node("P1.S1", "sect1", "same text")])
    web_tree = _node("P1", "part1", "same text", children=[_node("P1.S1", "sect1", "same text")])

    statuses = compare_trees(pdf_tree, [], web_tree, [], ALWAYS_MATCH, NEVER_MATCH)

    assert statuses["P1"] is True
    assert statuses["P1.S1"] is True


def test_mismatched_leaf_text_fails_and_propagates_to_the_parent():
    pdf_tree = _node("P1", "part1", "", children=[_node("P1.S1", "sect1", "pdf text")])
    web_tree = _node("P1", "part1", "", children=[_node("P1.S1", "sect1", "different text")])

    statuses = compare_trees(pdf_tree, [], web_tree, [], NEVER_MATCH, NEVER_MATCH)

    assert statuses["P1.S1"] is False
    assert statuses["P1"] is False


def test_node_missing_from_the_web_tree_fails():
    pdf_tree = _node("P1", "part1", "", children=[_node("P1.S1", "sect1", "text")])
    web_tree = _node("P1", "part1", "")  # no P1.S1 child at all

    statuses = compare_trees(pdf_tree, [], web_tree, [], ALWAYS_MATCH, NEVER_MATCH)

    assert statuses["P1.S1"] is False
    assert statuses["P1"] is False


def test_a_passing_sibling_is_unaffected_by_a_failing_sibling_but_the_parent_still_fails():
    # The failing sibling comes FIRST here - a regression test for all()
    # short-circuiting on the first False and never visiting (or recording
    # a status for) the passing sibling that follows it.
    pdf_tree = _node(
        "P1",
        "part1",
        "",
        children=[_node("P1.S1", "sect1", "bad"), _node("P1.S2", "sect2", "ok")],
    )
    web_tree = _node(
        "P1",
        "part1",
        "",
        children=[_node("P1.S1", "sect1", "bad"), _node("P1.S2", "sect2", "ok")],
    )

    def text_matches(a, b):
        return a != "bad"

    statuses = compare_trees(pdf_tree, [], web_tree, [], text_matches, NEVER_MATCH)

    assert statuses["P1.S1"] is False
    assert statuses["P1.S2"] is True
    assert statuses["P1"] is False


def test_an_owned_image_that_fails_to_match_fails_its_owning_node():
    pdf_tree = _node("P1", "part1", "text")
    web_tree = _node("P1", "part1", "text")
    pdf_images = [_image("P1.Fig1", "part1")]
    web_images = [_image("P1.Fig1", "part1")]

    statuses = compare_trees(pdf_tree, pdf_images, web_tree, web_images, ALWAYS_MATCH, NEVER_MATCH)

    assert statuses["P1.Fig1"] is False
    assert statuses["P1"] is False


def test_an_owned_image_that_matches_leaves_its_owning_node_passing():
    pdf_tree = _node("P1", "part1", "text")
    web_tree = _node("P1", "part1", "text")
    pdf_images = [_image("P1.Fig1", "part1")]
    web_images = [_image("P1.Fig1", "part1")]

    statuses = compare_trees(pdf_tree, pdf_images, web_tree, web_images, ALWAYS_MATCH, ALWAYS_MATCH)

    assert statuses["P1.Fig1"] is True
    assert statuses["P1"] is True


def test_an_image_with_no_web_counterpart_fails_without_calling_images_match():
    pdf_tree = _node("P1", "part1", "text")
    pdf_images = [_image("P1.Fig1", "part1")]

    def boom(pdf_image, web_image):
        raise AssertionError("images_match should not be called with no web counterpart")

    statuses = compare_trees(
        pdf_tree, pdf_images, _node("P1", "part1", "text"), [], ALWAYS_MATCH, boom
    )

    assert statuses["P1.Fig1"] is False
    assert statuses["P1"] is False


def test_container_node_with_empty_content_on_both_sides_is_a_trivial_own_match():
    # A pure structural container (e.g. a Volume/Part heading) may carry no
    # rendered text of its own - real_text_matches("", "") is a trivial pass
    # (see test_comparison_text_similarity.py); this exercises the engine's
    # own wiring of that rule via an injected matcher with the same shape.
    pdf_tree = _node("V", "volume", "", children=[_node("V.P1", "part1", "text")])
    web_tree = _node("V", "volume", "", children=[_node("V.P1", "part1", "text")])

    def text_matches(a, b):
        return (not a and not b) or a == b

    statuses = compare_trees(pdf_tree, [], web_tree, [], text_matches, NEVER_MATCH)

    assert statuses["V"] is True
    assert statuses["V.P1"] is True


def test_missing_web_tree_entirely_fails_every_node():
    pdf_tree = _node("P1", "part1", "text", children=[_node("P1.S1", "sect1", "text")])

    statuses = compare_trees(pdf_tree, [], None, [], ALWAYS_MATCH, ALWAYS_MATCH)

    assert statuses["P1"] is False
    assert statuses["P1.S1"] is False


def test_a_container_nodes_own_text_is_not_compared_against_the_webs_concatenated_descendant_text():
    # The web pipeline's own `content` for a node with children includes its
    # descendants' text too (concatenated); the PDF pipeline's holds only
    # that node's own immediate text. Comparing them directly would
    # spuriously fail almost every container node - a container's own text
    # is trivially ok once matched; only real leaves get a real text
    # comparison, and rollup covers the rest.
    pdf_tree = _node(
        "S1",
        "sent1",
        "This Code applies to the following:",
        children=[_node("S1.a", "sent1.a", "the design of a new building")],
    )
    web_tree = _node(
        "S1",
        "sent1",
        "This Code applies to the following: a) the design of a new building",
        children=[_node("S1.a", "sent1.a", "the design of a new building")],
    )

    def exact_match(a, b):
        return a == b

    statuses = compare_trees(pdf_tree, [], web_tree, [], exact_match, NEVER_MATCH)

    assert statuses["S1.a"] is True
    assert statuses["S1"] is True


def test_a_pdf_image_with_no_unified_number_is_ignored():
    pdf_tree = _node("P1", "part1", "text")
    pdf_images = [{"unified_number": "", "owner_citation": "part1"}]

    def boom(pdf_image, web_image):
        raise AssertionError("images_match should not be called for an unkeyed image")

    statuses = compare_trees(
        pdf_tree, pdf_images, _node("P1", "part1", "text"), [], ALWAYS_MATCH, boom
    )

    assert statuses["P1"] is True


def test_a_node_with_no_unified_number_is_not_recorded_but_its_children_still_are():
    pdf_tree = {
        "unified_number": "",
        "citation": "volume",
        "content": "",
        "children": [_node("P1", "part1", "text")],
    }
    web_tree = {
        "unified_number": "",
        "citation": "volume",
        "content": "",
        "children": [_node("P1", "part1", "text")],
    }

    statuses = compare_trees(pdf_tree, [], web_tree, [], ALWAYS_MATCH, NEVER_MATCH)

    assert "" not in statuses
    assert statuses["P1"] is True
