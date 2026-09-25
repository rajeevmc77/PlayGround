"""mo_toc's cross-source numbering rules: which shared.numbering.Rule builds
each Node.type's unified_number (see
ai_docs/2026-09-25-cross-source-unified-numbering-design.md)."""

from shared.numbering import Rule

_ABSOLUTE = Rule("absolute")

MO_TOC_RULES: dict[str, Rule] = {
    # The MO package is one volume; the volume never enters descendants' keys.
    "Volume": Rule("fixed", "V1"),
    "FrontMatter": Rule("fixed", "FM"),
    "BackMatter": Rule("fixed", "BM"),
    "Division": Rule("root"),
    "Appendix": Rule("root", "App"),
    "Part": _ABSOLUTE,
    "Section": _ABSOLUTE,
    "Subsection": _ABSOLUTE,
    "Article": _ABSOLUTE,
    "Note": _ABSOLUTE,
    "AppendixPart": _ABSOLUTE,
    "AppendixSection": _ABSOLUTE,
    "AppendixArticle": _ABSOLUTE,
    "Sentence": Rule("child"),
    "Clause": Rule("suffix"),
    "Subclause": Rule("suffix"),
    "NotesContainer": Rule("literal", "Notes"),
    # The web's "spectables" pages; same ordinal prefix so the two line up.
    "TableGroup": Rule("ordinal", "Spec"),
    "Table": Rule("ordinal", "Tbl", scoped=True),
    "Row": Rule("ordinal", "Row"),
    "Cell": Rule("ordinal", "Col"),
}

# Nodes that own tables/images for ordinal counting. Appendix sub-levels are
# deliberately absent: the web keeps Appendix C/D tables directly under the
# appendix, so the PDF counts them there too (Appendix restarts the chain,
# which already makes it a scope).
MO_TOC_SCOPE_TYPES: frozenset[str] = frozenset(
    {"Part", "Section", "Subsection", "Article", "NotesContainer", "Note", "TableGroup"}
)
