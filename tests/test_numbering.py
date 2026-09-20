from dataclasses import dataclass, field

from shared.numbering import assign_unified_numbers


@dataclass
class _StubNode:
    type: str
    children: list["_StubNode"] = field(default_factory=list)
    unified_number: str = ""


def test_assigns_plain_numbers_for_canonical_types():
    article = _StubNode(type="article")
    part = _StubNode(type="part", children=[article])
    volume = _StubNode(type="volume", children=[part])
    markers = {"volume": None, "part": None, "article": None}

    assign_unified_numbers([volume], markers)

    assert volume.unified_number == "1"
    assert part.unified_number == "1.1"
    assert article.unified_number == "1.1.1"


def test_counts_positions_per_type_not_globally():
    part_a = _StubNode(type="part")
    notes = _StubNode(type="notes")
    part_b = _StubNode(type="part")
    markers = {"part": None, "notes": "Notes"}

    assign_unified_numbers([part_a, notes, part_b], markers)

    assert part_a.unified_number == "1"
    assert notes.unified_number == "Notes1"
    assert part_b.unified_number == "2"


def test_marker_type_gets_prefixed_segment():
    appendix = _StubNode(type="appendix")
    part = _StubNode(type="part", children=[appendix])
    markers = {"part": None, "appendix": "App"}

    assign_unified_numbers([part], markers)

    assert appendix.unified_number == "1.App1"


def test_nested_marker_chain():
    appendix_part = _StubNode(type="appendix_part")
    appendix = _StubNode(type="appendix", children=[appendix_part])
    markers = {"appendix": "App", "appendix_part": "AppPt"}

    assign_unified_numbers([appendix], markers)

    assert appendix.unified_number == "App1"
    assert appendix_part.unified_number == "App1.AppPt1"


def test_unmapped_type_falls_back_to_type_name_as_marker():
    mystery = _StubNode(type="mystery")
    markers = {"part": None}

    assign_unified_numbers([mystery], markers)

    assert mystery.unified_number == "mystery1"


def test_leaf_node_with_no_children_does_not_crash():
    leaf = _StubNode(type="article", children=[])

    assign_unified_numbers([leaf], {"article": None})

    assert leaf.unified_number == "1"


def test_multiple_top_level_siblings_get_sequential_numbers():
    vol1 = _StubNode(type="volume")
    vol2 = _StubNode(type="volume")

    assign_unified_numbers([vol1, vol2], {"volume": None})

    assert vol1.unified_number == "1"
    assert vol2.unified_number == "2"


def test_parent_number_is_prefixed_when_given():
    child = _StubNode(type="section")

    assign_unified_numbers([child], {"section": None}, parent_number="9")

    assert child.unified_number == "9.1"


def test_position_above_nine_is_not_zero_padded():
    siblings = [_StubNode(type="article") for _ in range(10)]

    assign_unified_numbers(siblings, {"article": None})

    assert siblings[9].unified_number == "10"
