"""Assigns a dotted unified_number to every node in a tree - positional by
default, with two opt-in overrides selected by node type.

Duck-types on any object exposing `.type`, `.children`, `.identifier`, and a
settable `.unified_number` — no dependency on any specific domain model.
"""


def assign_unified_numbers(
    nodes: list,
    type_to_marker: dict[str, str | None],
    parent_number: str = "",
    identifier_types: frozenset[str] = frozenset(),
    suffix_types: frozenset[str] = frozenset(),
) -> None:
    counters: dict[str, int] = {}
    for node in nodes:
        counters[node.type] = counters.get(node.type, 0) + 1
        node.unified_number = _number_for(
            node, counters[node.type], parent_number, type_to_marker, identifier_types, suffix_types
        )
        assign_unified_numbers(
            node.children, type_to_marker, node.unified_number, identifier_types, suffix_types
        )


def _number_for(
    node,
    position: int,
    parent_number: str,
    type_to_marker: dict[str, str | None],
    identifier_types: frozenset[str],
    suffix_types: frozenset[str],
) -> str:
    if node.type in suffix_types:
        return f"{parent_number}{node.identifier}"
    if node.type in identifier_types:
        segment = node.identifier
    else:
        is_canonical = node.type in type_to_marker and type_to_marker[node.type] is None
        marker = "" if is_canonical else type_to_marker.get(node.type, node.type)
        segment = str(position) if is_canonical else f"{marker}{position}"
    return f"{parent_number}.{segment}" if parent_number else segment
