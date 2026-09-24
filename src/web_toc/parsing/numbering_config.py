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
    "Table": "Tbl",
}

# Division numbers by its lettered identifier (e.g. "B") instead of position;
# Row, Cell, and Sentence number by their own identifier (e.g. "row1", "col1",
# "(1)") directly - same convention as mo_toc's MO_TOC_IDENTIFIER_TYPES.
WEB_TOC_IDENTIFIER_TYPES: frozenset[str] = frozenset({"division", "Row", "Cell", "Sentence"})

# Clause/Subclause already carry their display label - "(a)", "(i)" - in
# WebNode.identifier; append it directly with no dot, run onto the Sentence
# segment - e.g. "...(1)(a)(i)". Same convention as mo_toc's
# MO_TOC_SUFFIX_TYPES.
WEB_TOC_SUFFIX_TYPES: frozenset[str] = frozenset({"Clause", "Subclause"})
