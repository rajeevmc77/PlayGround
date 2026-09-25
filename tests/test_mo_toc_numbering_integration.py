from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
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


def test_real_mo_toc_tree_gets_cross_source_keys():
    subclause = _node("Subclause", "(i)", "A-1.1.1.1.(1)(a)(i)")
    clause = _node("Clause", "(a)", "A-1.1.1.1.(1)(a)", children=[subclause])
    table = _node("Table", "1.1.1.1.", "Table:1.1.1.1.")
    sentence = _node("Sentence", "(1)", "A-1.1.1.1.(1)", children=[clause, table])
    article = _node("Article", "1.1.1.1.", "A-1.1.1.1.", children=[sentence])
    subsection = _node("Subsection", "1.1.1.", "A-1.1.1.", children=[article])
    section = _node("Section", "1.1.", "A-1.1.", children=[subsection])
    note = _node("Note", "A-1.1.1.1.(3)", "Note:A-1.1.1.1.(3)")
    notes = _node("NotesContainer", "1", "Notes-A-1", children=[note])
    part = _node("Part", "1", "A-1", children=[section, notes])
    division = _node("Division", "A", "A", children=[part])
    front = _node("FrontMatter", "FrontMatter", "FrontMatter")
    volume = _node("Volume", "Volume", "Volume", children=[front, division])

    scope = assign_unified_numbers([volume], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)

    assert volume.unified_number == "V1"
    assert front.unified_number == "FM"
    assert division.unified_number == "A"
    assert part.unified_number == "A.1"
    assert section.unified_number == "A.1.1"
    assert subsection.unified_number == "A.1.1.1"
    assert article.unified_number == "A.1.1.1.1"
    assert sentence.unified_number == "A.1.1.1.1.(1)"
    assert clause.unified_number == "A.1.1.1.1.(1)(a)"
    assert subclause.unified_number == "A.1.1.1.1.(1)(a)(i)"
    assert table.unified_number == "A.1.1.1.1.Tbl1"
    assert notes.unified_number == "A.1.Notes"
    assert note.unified_number == "A.A-1.1.1.1.(3)"
    assert scope["A-1.1.1.1.(1)(a)(i)"] == "A.1.1.1.1"
