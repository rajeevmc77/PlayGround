"""web_toc's cross-source numbering rules - the web counterpart of
mo_toc.parsing.numbering_config, built so both produce the same key for the
same node. The synthetic "root" wrapper is never numbered (only its children
are passed in)."""

from shared.numbering import Rule

_ABSOLUTE = Rule("absolute")

WEB_TOC_RULES: dict[str, Rule] = {
    "volume": Rule("root", "V"),
    # The unnumbered "Preface" division is the PDF's front matter.
    "division": Rule("root", fallback="FM"),
    "division_appendix": Rule("root", "App"),
    "part": _ABSOLUTE,
    "section": _ABSOLUTE,
    "subsection": _ABSOLUTE,
    "article": _ABSOLUTE,
    "Note": _ABSOLUTE,
    "Sentence": Rule("child"),
    "Clause": Rule("suffix"),
    "Subclause": Rule("suffix"),
    "part_appendix": Rule("literal", "Notes"),
    "spectables": Rule("ordinal", "Spec"),
    "index": Rule("ordinal", "Idx"),
    "conversions": Rule("ordinal", "Conv"),
    "Table": Rule("ordinal", "Tbl", scoped=True),
    "Row": Rule("ordinal", "Row"),
    "Cell": Rule("ordinal", "Col"),
}

WEB_TOC_SCOPE_TYPES: frozenset[str] = frozenset(
    {
        "part",
        "section",
        "subsection",
        "article",
        "part_appendix",
        "Note",
        "spectables",
        "index",
        "conversions",
    }
)
