"""Maps mo_toc Node.type values to a unified-numbering marker: None for one of
the nine canonical document levels, or a short prefix for everything else."""

MO_TOC_TYPE_MARKERS: dict[str, str | None] = {
    "Volume": None,
    "Division": None,
    "Part": None,
    "Section": None,
    "Subsection": None,
    "Article": None,
    "Sentence": None,
    "Clause": None,
    "Subclause": None,
    "FrontMatter": "FM",
    "BackMatter": "BM",
    "Appendix": "App",
    "AppendixPart": "AppPt",
    "AppendixSection": "AppSec",
    "AppendixArticle": "AppArt",
    "NotesContainer": "Notes",
    "Note": "Note",
    "TableGroup": "Tbl",
}

# Division numbers by its lettered identifier (e.g. "B") instead of position;
# Sentence numbers by its own display label (e.g. "(1)") the same way, still
# dot-joined onto its parent Article - e.g. "...6.5.(1)".
MO_TOC_IDENTIFIER_TYPES: frozenset[str] = frozenset({"Division", "Sentence"})

# Clause/Subclause already carry their display label - "(a)", "(i)" - in
# Node.identifier; append it directly with no dot, run onto the Sentence
# segment - e.g. "...6.5.(1)(a)(i)".
MO_TOC_SUFFIX_TYPES: frozenset[str] = frozenset({"Clause", "Subclause"})
