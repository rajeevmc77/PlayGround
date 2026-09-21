"""Maps web_toc WebNode.type values to a unified-numbering marker: None for one
of the six canonical document levels this tree reaches, or a short prefix for
everything else. The synthetic "root" wrapper node is deliberately absent —
it is never passed to assign_unified_numbers (only its children are)."""

WEB_TOC_TYPE_MARKERS: dict[str, str | None] = {
    "volume": None,
    "division": None,
    "part": None,
    "section": None,
    "subsection": None,
    "article": None,
    "part_appendix": "App",
    "division_appendix": "App",
    "index": "Idx",
    "conversions": "Conv",
    "spectables": "Spec",
}

# Division numbers by its lettered identifier (e.g. "B") instead of position.
WEB_TOC_IDENTIFIER_TYPES: frozenset[str] = frozenset({"division"})

# web_toc has no Sentence/Clause/Subclause-equivalent nodes today.
WEB_TOC_SUFFIX_TYPES: frozenset[str] = frozenset()
