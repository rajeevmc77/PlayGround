"""Pairs a table's PDF rows with its web rows by content, not position.

Rows are numbered by position on both sides, so one row present on only one
side (B.9.38.1.1 has 88 more on the web; a PDF row split by a page break
used to add one) shifted every row below it, and the cells compared were
never the same cells. Here rows are aligned on their whole text (whitespace
dropped, quotes and dashes made plain - the comparison's own rule, see
shared/styled_text.py): identical runs pair one-to-one, a block of differing
rows pairs by position inside the block - so a table with no identical rows
at all falls back to plain positional pairing - and a row only one side has
stays unpaired. Cells pair by column within paired rows. Pure: dicts in,
dict out.

Tables within one article/note are paired the same way, on their titles
(table_pairs): B.A-9.36.2.4.(1)'s web note has four untitled worked-example
tables among its four captioned ones, so by position every PDF table met the
wrong web table.
"""

import re
from difflib import SequenceMatcher

from shared.styled_text import StyledText


def _row_key(row: dict) -> str:
    cells = (StyledText(c.get("content") or "").signature() for c in row.get("children", []))
    return "|".join("".join(char for char, _ in signature) for signature in cells)


def _pairs(pdf_keys: list[str], web_keys: list[str]) -> dict[int, int]:
    """Identical runs pair one-to-one; a block of differing keys pairs by
    position inside the block; a key only one side has stays unpaired."""
    matcher = SequenceMatcher(None, pdf_keys, web_keys, autojunk=False)
    pairs: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            pairs.update(zip(range(i1, i2), range(j1, j2), strict=False))
    return pairs


def _row_pairs(pdf_rows: list[dict], web_rows: list[dict]) -> dict[int, int]:
    return _pairs([_row_key(r) for r in pdf_rows], [_row_key(r) for r in web_rows])


# What differs between the two sides' titles for the same table: the PDF
# appends its "Forming Part of Sentence ..." line; footnote markers are "(1)"
# in the PDF and "^{(1)}" in the site's LaTeX, subscripts "_{1}".
_FORMING_PART_OF = re.compile(r"\s*Forming [Pp]art of .*$")
_FOOTNOTE = re.compile(r"\^\{\(\d+\)\}|\(\d+\)")
_NOT_WORD = re.compile(r"[\W_]+")


def _title_key(table: dict, untitled: str) -> str:
    title = _FORMING_PART_OF.sub("", table.get("title") or "")
    key = _NOT_WORD.sub("", _FOOTNOTE.sub("", title)).lower()
    return key or untitled


def table_pairs(pdf_tables: list[dict], web_tables: list[dict]) -> dict[int, int]:
    """PDF table index -> its web table's index, by title. An untitled table
    never matches by title, so it pairs only by position in a differing block."""
    pdf_keys = [_title_key(t, f"\0pdf{i}") for i, t in enumerate(pdf_tables)]
    web_keys = [_title_key(t, f"\0web{i}") for i, t in enumerate(web_tables)]
    return _pairs(pdf_keys, web_keys)


def _cell_counterparts(pdf_row: dict, web_row: dict | None) -> dict[str, str | None]:
    web_cells = web_row.get("children", []) if web_row else []
    return {
        cell["unified_number"]: web_cells[col]["unified_number"] if col < len(web_cells) else None
        for col, cell in enumerate(pdf_row.get("children", []))
    }


def table_counterparts(pdf_table: dict, web_table: dict) -> dict[str, str | None]:
    """PDF row/cell unified_number -> its web counterpart's (None: unpaired)."""
    pdf_rows, web_rows = pdf_table.get("children", []), web_table.get("children", [])
    pairs = _row_pairs(pdf_rows, web_rows)
    counterparts: dict[str, str | None] = {}
    for index, pdf_row in enumerate(pdf_rows):
        web_row = web_rows[pairs[index]] if index in pairs else None
        counterparts[pdf_row["unified_number"]] = web_row["unified_number"] if web_row else None
        counterparts.update(_cell_counterparts(pdf_row, web_row))
    return counterparts
