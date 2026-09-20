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
