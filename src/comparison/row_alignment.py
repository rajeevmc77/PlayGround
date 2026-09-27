"""Pairs a table's PDF rows with its web rows by content, not position.

Rows are numbered by position on both sides, so one row present on only one
side (B.9.38.1.1 has 88 more on the web; a PDF row split by a page break
used to add one) shifted every row below it, and the cells compared were
never the same cells. Here rows are aligned on their whole text (whitespace
dropped, quotes and dashes made plain - the comparison's own rule, see
shared/styled_text.py): identical runs pair one-to-one, and a row only one
side has stays unpaired. Inside a block of differing rows, rows sharing most
of their words pair first, in order, and the rows left between them pair by
position - Table 1.3.1.2. has no identical rows at all (the site writes
"Note A-..." in every last column), and by position alone each row only one
side had shifted every row below it. A block with no similar rows, or with
as many rows on each side, is all by position. Cells pair within paired
rows the same way, on their text (_cell_counterparts). Pure: dicts in, dict
out.

Tables within one article/note are paired the same way, on their titles
(table_pairs): B.A-9.36.2.4.(1)'s web note has four untitled worked-example
tables among its four captioned ones, so by position every PDF table met the
wrong web table.
"""

import re
from difflib import SequenceMatcher

from shared.styled_text import StyledText


def _cell_key(cell: dict) -> str:
    return "".join(char for char, _ in StyledText(cell.get("content") or "").signature())


def _row_key(row: dict) -> str:
    return "|".join(_cell_key(cell) for cell in row.get("children", []))


def _positional(n: int, m: int) -> list[tuple[int, int]]:
    return list(zip(range(n), range(m), strict=False))


def _by_position(n: int, m: int, _i1: int, _j1: int) -> list[tuple[int, int]]:
    return _positional(n, m)


def _pairs(pdf_keys: list, web_keys: list, pair_block=_by_position) -> dict[int, int]:
    """Identical runs pair one-to-one; a key only one side has stays
    unpaired; a block of differing keys - n PDF keys from i1, m web keys
    from j1 - pairs by `pair_block(n, m, i1, j1)`, which returns
    block-local index pairs: by position unless told otherwise."""
    matcher = SequenceMatcher(None, pdf_keys, web_keys, autojunk=False)
    pairs: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.update(zip(range(i1, i2), range(j1, j2), strict=False))
        elif tag == "replace":
            pairs.update((i1 + i, j1 + j) for i, j in pair_block(i2 - i1, j2 - j1, i1, j1))
    return pairs


# Rows differing only a little (the site's "Note A-..." for the PDF's
# "A-...", an extra reference) share most of their words.
SIMILAR_ROW = 0.5


def _words(row: dict) -> frozenset[str]:
    return frozenset(
        word
        for cell in row.get("children", [])
        for word in (cell.get("content") or "").lower().split()
    )


def _similarity(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def _best_scores(pdf_words: list, web_words: list) -> list[list[float]]:
    """score[i][j]: the most total similarity pairing the first i PDF rows
    with the first j web rows in order, pairing only similar rows."""
    score = [[0.0] * (len(web_words) + 1) for _ in range(len(pdf_words) + 1)]
    for i, a in enumerate(pdf_words, start=1):
        for j, b in enumerate(web_words, start=1):
            sim = _similarity(a, b)
            paired = score[i - 1][j - 1] + sim if sim >= SIMILAR_ROW else 0.0
            score[i][j] = max(score[i - 1][j], score[i][j - 1], paired)
    return score


def _anchors(pdf_words: list, web_words: list) -> list[tuple[int, int]]:
    """The similar pairs of the best in-order pairing, first to last."""
    score = _best_scores(pdf_words, web_words)
    i, j, anchors = len(pdf_words), len(web_words), []
    while i and j:
        if score[i][j] == score[i - 1][j]:
            i -= 1
        elif score[i][j] == score[i][j - 1]:
            j -= 1
        else:
            anchors.append((i - 1, j - 1))
            i, j = i - 1, j - 1
    return anchors[::-1]


def _with_gaps_by_position(anchors: list[tuple[int, int]], n: int, m: int) -> list[tuple[int, int]]:
    """Anchors, plus the rows between two of them paired by position."""
    pairs, prev_i, prev_j = [], -1, -1
    for i, j in [*anchors, (n, m)]:
        gap = _positional(i - prev_i - 1, j - prev_j - 1)
        pairs.extend((prev_i + 1 + a, prev_j + 1 + b) for a, b in gap)
        pairs.append((i, j))
        prev_i, prev_j = i, j
    return pairs[:-1]


def _row_pairs(pdf_rows: list[dict], web_rows: list[dict]) -> dict[int, int]:
    """Inside a block of differing rows, similar rows pair first (so a row
    only one side has no longer shifts the rest) and the rows left between
    them by position - a block with no similar rows is all by position.
    A block with as many rows on each side stays by position: no row is
    missing there, and a spanning cell's text split differently (Table
    3.1.8.17.) can make the wrong row look the most similar."""

    def by_similarity(n: int, m: int, i1: int, j1: int) -> list[tuple[int, int]]:
        if n == m:
            return _positional(n, m)
        pdf_words = [_words(r) for r in pdf_rows[i1 : i1 + n]]
        web_words = [_words(r) for r in web_rows[j1 : j1 + m]]
        return _with_gaps_by_position(_anchors(pdf_words, web_words), n, m)

    return _pairs([_row_key(r) for r in pdf_rows], [_row_key(r) for r in web_rows], by_similarity)


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
    """Cells pair the way rows do: identical ones first, differing ones by
    position between them. The site lists only the cells a row starts, so a
    row under a span starts further right in the PDF; and the PDF places a
    colspan cell's text in the middle of its span, the site in its first
    column - by column index, neither met its counterpart. An empty cell is
    never identical to another: matched mid-row, two empty cells dragged the
    rest of the row out of line (Table 9.23.13.7.-A)."""
    pdf_cells = pdf_row.get("children", [])
    web_cells = (web_row or {}).get("children", [])
    pairs = _pairs(_cell_keys(pdf_cells, "pdf"), _cell_keys(web_cells, "web"))
    web_numbers = [cell["unified_number"] for cell in web_cells]
    return {
        cell["unified_number"]: web_numbers[pairs[col]] if col in pairs else None
        for col, cell in enumerate(pdf_cells)
    }


def _cell_keys(cells: list[dict], side: str) -> list[str]:
    """Each cell's text key; an empty cell's key is its own, so it's never
    identical to another cell."""
    return [_cell_key(cell) or f"\0{side}{i}" for i, cell in enumerate(cells)]


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
