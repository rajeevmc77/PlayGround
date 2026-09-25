"""Moves each "Notes to Part N" container from beside the Parts - where the
rank-based tree builder leaves it, since NotesContainer shares Part's rank -
into Part N of the same Division as that Part's last child: the website's
own layout. Runs after build_tree_from_lines, so the builder's own
stack-close logic is untouched."""

from mo_toc.domain.models import Node


def nest_notes_under_parts(volume: Node) -> None:
    for division in volume.children:
        if division.type == "Division":
            _nest_in_division(division)


def _nest_in_division(division: Node) -> None:
    parts = {child.identifier: child for child in division.children if child.type == "Part"}
    kept = []
    for child in division.children:
        if child.type != "NotesContainer":
            kept.append(child)
            continue
        _move_into_part(child, parts, division)
    division.children = kept


def _move_into_part(notes: Node, parts: dict[str, Node], division: Node) -> None:
    part = parts.get(notes.identifier)
    if part is None:
        raise ValueError(
            f"{notes.citation}: no Part {notes.identifier} in Division {division.identifier}"
        )
    part.children.append(notes)
    part.end_page = max(part.end_page, notes.end_page)
