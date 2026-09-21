from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)
from shared.numbering import assign_unified_numbers


def _node(
    node_type: str, identifier: str, citation: str, children: list[Node] | None = None
) -> Node:
    return Node(
        type=node_type,
        identifier=identifier,
        citation=citation,
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
        children=children or [],
    )


def test_assign_unified_numbers_against_real_mo_toc_node_tree():
    subclause = _node("Subclause", "(i)", "A-1.1.1(1)(a)(i)")
    clause = _node("Clause", "(a)", "A-1.1.1(1)(a)", children=[subclause])
    sentence = _node("Sentence", "(1)", "A-1.1.1(1)", children=[clause])
    article = _node("Article", "1", "A-1.1.1", children=[sentence])
    section = _node("Section", "1.1", "A-1.1", children=[article])
    notes = _node("NotesContainer", "1", "Notes-A-1")
    part = _node("Part", "1", "A-1", children=[section, notes])
    division = _node("Division", "A", "A", children=[part])
    volume = _node("Volume", "", "Volume", children=[division])

    assign_unified_numbers(
        [volume],
        MO_TOC_TYPE_MARKERS,
        identifier_types=MO_TOC_IDENTIFIER_TYPES,
        suffix_types=MO_TOC_SUFFIX_TYPES,
    )

    assert volume.unified_number == "1"
    assert division.unified_number == "1.A"
    assert part.unified_number == "1.A.1"
    assert section.unified_number == "1.A.1.1"
    assert article.unified_number == "1.A.1.1.1"
    assert sentence.unified_number == "1.A.1.1.1.(1)"
    assert clause.unified_number == "1.A.1.1.1.(1)(a)"
    assert subclause.unified_number == "1.A.1.1.1.(1)(a)(i)"
    assert notes.unified_number == "1.A.1.Notes1"
