from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.numbering_config import MO_TOC_TYPE_MARKERS
from shared.numbering import assign_unified_numbers


def test_assign_unified_numbers_against_real_mo_toc_node_tree():
    section = Node(
        type="Section",
        identifier="1.1",
        citation="A-1.1",
        title="General",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    notes = Node(
        type="NotesContainer",
        identifier="1",
        citation="Notes-A-1",
        title="",
        page=5,
        end_page=6,
        bbox=BBox(0, 0, 0, 0),
    )
    part = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="Compliance",
        page=1,
        end_page=5,
        bbox=BBox(0, 0, 0, 0),
        children=[section],
    )
    division = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=1,
        end_page=10,
        bbox=BBox(0, 0, 0, 0),
        children=[part, notes],
    )
    volume = Node(
        type="Volume",
        identifier="",
        citation="Volume",
        title="",
        page=1,
        end_page=100,
        bbox=BBox(0, 0, 0, 0),
        children=[division],
    )

    assign_unified_numbers([volume], MO_TOC_TYPE_MARKERS)

    assert volume.unified_number == "1"
    assert division.unified_number == "1.1"
    assert part.unified_number == "1.1.1"
    assert section.unified_number == "1.1.1.1"
    assert notes.unified_number == "1.1.Notes1"
