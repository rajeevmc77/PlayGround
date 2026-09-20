"""Line -> heading/caption classification, gated by font weight so a body-text
citation reference (e.g. "...as required in Subsection 3.1.3.1...") is never
mistaken for a real heading. Real Division/Part/.../Article/Appendix/TableGroup
headings render in Arial-Black; the front/back-matter administrative marker
("PROVINCE OF BRITISH COLUMBIA") renders in Arial-BoldMT — distinct required
font substrings per pattern, not one blanket gate, since "Bold" and "Black" are
different words that never both appear in the same font name in this document.
"""

import re

RE_DIVISION = re.compile(r"^Division\s+([A-Z])\s*$")
RE_NOTES_CONTAINER = re.compile(r"^Notes to Part\s+(\d+)\s*$")
RE_PART = re.compile(r"^Part\s+(\d+)\s*$")
RE_SECTION = re.compile(r"^Section\s+(\d+\.\d+)\.\s*(.*)$")
# `\s*` not `\s+`: two Articles in this PDF's text extraction have no space
# between number and title ("3.2.2.64.Group D..."). Checked before Subsection
# in HEADING_PATTERNS, so a 4-part number is always claimed here first.
RE_ARTICLE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)\.\s*(.*)$")
RE_SUBSECTION = re.compile(r"^(\d+\.\d+\.\d+)\.\s+(.*)$")
RE_TABLE_GROUP = re.compile(r"^[A-Z][A-Za-z ]*\bTables\s*$")
RE_APPENDIX = re.compile(r"^Appendix\s+([A-Z])\s*$")
RE_APPENDIX_PART = re.compile(r"^Section\s+([A-Z])-(\d+)\s+(.*)$")
RE_APPENDIX_ARTICLE = re.compile(r"^([A-Z])-(\d+\.\d+\.\d+)\.\s+(.*)$")
RE_APPENDIX_SECTION = re.compile(r"^([A-Z])-(\d+\.\d+)\.\s+(.*)$")
RE_BACK_MATTER_MARKER = re.compile(r"^PROVINCE OF BRITISH COLUMBIA$")
RE_CAPTION = re.compile(r"^(Table|Figure)\s+(\S.*)$")

# (type, pattern, required substring somewhere in the line's font name)
HEADING_PATTERNS = [
    ("Division", RE_DIVISION, "Black"),
    ("NotesContainer", RE_NOTES_CONTAINER, "Black"),
    ("Part", RE_PART, "Black"),
    ("Section", RE_SECTION, "Black"),
    ("Article", RE_ARTICLE, "Black"),
    ("Subsection", RE_SUBSECTION, "Black"),
    ("Appendix", RE_APPENDIX, "Black"),
    ("AppendixPart", RE_APPENDIX_PART, "Black"),
    ("AppendixArticle", RE_APPENDIX_ARTICLE, "Black"),
    ("AppendixSection", RE_APPENDIX_SECTION, "Black"),
    ("TableGroup", RE_TABLE_GROUP, "Black"),
    ("BackMatter", RE_BACK_MATTER_MARKER, "Bold"),
]

RANK = {
    "Division": 1,
    "Part": 2,
    "NotesContainer": 2,
    "Section": 3,
    "Subsection": 4,
    "Article": 5,
    "Note": 6,
    "Appendix": 1,
    "AppendixPart": 2,
    "AppendixSection": 3,
    "AppendixArticle": 5,
    "TableGroup": 3,
    "FrontMatter": 1,
    "BackMatter": 1,
}

ARTICLE_TYPES = ("Article", "AppendixArticle")


def classify_heading_line(text: str, font: str) -> tuple[str, re.Match] | None:
    for ntype, pattern, required_font in HEADING_PATTERNS:
        if required_font not in font:
            continue
        match = pattern.match(text)
        if match:
            return ntype, match
    return None


def classify_caption_line(text: str, font: str) -> re.Match | None:
    if "Bold" not in font or "Black" in font or "Narrow" in font:
        return None
    return RE_CAPTION.match(text)
