import pytest

from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.notes_nesting import nest_notes_under_parts


def _node(node_type, identifier, children=None, page=1, end_page=1):
    return Node(
        type=node_type,
        identifier=identifier,
        citation=f"{node_type}-{identifier}",
        title="",
        page=page,
        end_page=end_page,
        bbox=BBox(0, 0, 0, 0),
        children=children or [],
    )


def _volume(*division_children, division="A"):
    return _node("Volume", "Volume", [_node("Division", division, list(division_children))])


def test_notes_container_moves_to_end_of_matching_part():
    section = _node("Section", "1.1.")
    part1 = _node("Part", "1", [section], page=1, end_page=9)
    notes1 = _node("NotesContainer", "1", page=10, end_page=12)
    part2 = _node("Part", "2", page=13, end_page=20)
    volume = _volume(part1, notes1, part2)

    nest_notes_under_parts(volume)

    division = volume.children[0]
    assert division.children == [part1, part2]
    assert part1.children == [section, notes1]
    assert part1.end_page == 12


def test_part_without_notes_is_untouched():
    part2 = _node("Part", "2")
    volume = _volume(part2)

    nest_notes_under_parts(volume)

    assert part2.children == []


def test_notes_container_without_matching_part_raises():
    volume = _volume(_node("Part", "1"), _node("NotesContainer", "7"))

    with pytest.raises(ValueError, match="Part 7"):
        nest_notes_under_parts(volume)


def test_non_division_children_of_volume_are_ignored():
    front = _node("FrontMatter", "FrontMatter")
    volume = _node("Volume", "Volume", [front])

    nest_notes_under_parts(volume)

    assert volume.children == [front]
