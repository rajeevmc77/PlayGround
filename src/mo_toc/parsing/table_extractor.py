"""Detects tables from a Table-kind caption anchor plus the page's own
vector-drawn gridlines (PdfSource.page_drawing_rects), building a
Table -> Row -> Cell subtree per detected grid, one page at a time.

Anchored, not blind: rather than scanning every page for grid-shaped rects
(risking false positives on ordinary boxes/borders), detection starts from
a Table caption line, already reliably found via classify_caption_line.
Multi-page stitching and owner attachment are a separate pass (see
stitch_continuations/attach_tables) since they need the full tree.
"""

import itertools
import re
from dataclasses import dataclass

from mo_toc.domain.models import BBox, Caption, Node
from mo_toc.parsing.heading_rules import (
    classify_caption_line,
    is_caption_font,
    is_caption_title_font,
)
from mo_toc.parsing.image_matcher import assign_owner
from mo_toc.parsing.pdf_source import PageLine
from shared.styled_text import StyledText

RE_FORMING_PART_OF = re.compile(
    r"^Forming [Pp]art of (Sentence|Clause|Subclause|Article|Section|Subsection)\s+(.+?)\.?$"
)

LINE_THICKNESS_MAX = 2.0  # pt; a gridline rect's thin dimension
BOUNDARY_MERGE_TOLERANCE = 2.0  # pt; nearby edges from adjacent segments are one boundary
MIN_TABLE_ROWS = 2  # header + at least one data row
MIN_TABLE_COLS = 2
# A caption-anchored table's own page can legitimately hold only its header
# band - a single row-boundary pair, bordered top and bottom, with no
# internal divider - when the data rows continue on a later, caption-less
# page (confirmed on the real document: Table 9.10.14.5.-A's page 794).
# build_continuation_region already accepts a caption-less candidate page
# down to 1 row; build_table_region uses this same floor for its own
# anchor-page grid, since a genuine "Table X" caption match is already a
# stronger signal than a continuation page has to lean on. MIN_TABLE_ROWS
# stays the (stricter) bar for rects_form_a_grid, which has no caption
# anchor at all and needs the unambiguous multi-row signal instead.
MIN_ANCHOR_TABLE_ROWS = 1


@dataclass
class TableAnchor:
    page_index: int
    caption_line_idx: int
    identifier: str


@dataclass
class TableRegion:
    anchor: TableAnchor
    table_node: Node
    forming_part_of: tuple[str, str] | None
    consumed_line_indices: set[int]
    has_bottom_border: bool
    outer_bbox: BBox
    # The grid's column rules - a cell's bbox hugs its text, not the grid -
    # and those of them that run the grid's full height.
    col_xs: tuple[float, ...] = ()
    through_xs: tuple[float, ...] = ()


def find_table_anchors(lines: list[PageLine], page_index: int) -> list[TableAnchor]:
    anchors = []
    for idx, pline in enumerate(lines):
        cap_match = classify_caption_line(pline.text, pline.font, pline.centred)
        if cap_match and cap_match.group(1) == "Table":
            anchors.append(
                TableAnchor(
                    page_index=page_index,
                    caption_line_idx=idx,
                    identifier=cap_match.group(2).strip(),
                )
            )
    return anchors


def _classify_rect(rect: tuple[float, float, float, float]) -> str | None:
    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    if width > height and height <= LINE_THICKNESS_MAX and width > LINE_THICKNESS_MAX:
        return "horizontal"
    if height > width and width <= LINE_THICKNESS_MAX and height > LINE_THICKNESS_MAX:
        return "vertical"
    return None


def _merge_boundaries(values: list[float]) -> list[float]:
    merged = []
    for v in sorted(values):
        if merged and v - merged[-1] <= BOUNDARY_MERGE_TOLERANCE:
            continue
        merged.append(v)
    return merged


def _in_band(
    rect: tuple[float, float, float, float], below_y: float, above_y: float | None
) -> bool:
    y0 = rect[1]
    return y0 >= below_y - BOUNDARY_MERGE_TOLERANCE and (above_y is None or y0 <= above_y)


def _on_column_edge(x: float, col_xs: list[float]) -> bool:
    tolerance = BOUNDARY_MERGE_TOLERANCE
    outside = x <= col_xs[0] + tolerance or x >= col_xs[-1] - tolerance
    return outside or any(abs(x - col_x) <= tolerance for col_x in col_xs)


def _is_row_rule(rect: tuple[float, float, float, float], col_xs: list[float]) -> bool:
    """A row rule runs from column edge to column edge (or past the grid's
    outer edges). The marked-up PDF also underlines revised words - Table
    9.23.13.7.-C's heading has a short rule under each line - and those
    start and stop inside a cell."""
    return bool(col_xs) and _on_column_edge(rect[0], col_xs) and _on_column_edge(rect[2], col_xs)


def _rules_of_kind(rects: list, kind: str) -> list:
    return [rect for rect in rects if _classify_rect(rect) == kind]


def _grid_boundaries(
    rects: list[tuple[float, float, float, float]], below_y: float, above_y: float | None = None
) -> tuple[list[float], list[float]]:
    in_band = [rect for rect in rects if _in_band(rect, below_y, above_y)]
    col_xs = _merge_boundaries([(r[0] + r[2]) / 2 for r in _rules_of_kind(in_band, "vertical")])
    row_rules = [r for r in _rules_of_kind(in_band, "horizontal") if _is_row_rule(r, col_xs)]
    return _merge_boundaries([(r[1] + r[3]) / 2 for r in row_rules]), col_xs


def _rule_extent(x: float, verticals: list) -> tuple[float, float]:
    """The topmost and lowest y the vertical rules at `x` reach."""
    near = [
        rect for rect in verticals if abs((rect[0] + rect[2]) / 2 - x) <= BOUNDARY_MERGE_TOLERANCE
    ]
    return min(rect[1] for rect in near), max(rect[3] for rect in near)


def _runs_full_height(x: float, verticals: list, top: float, bottom: float) -> bool:
    rule_top, rule_bottom = _rule_extent(x, verticals)
    tolerance = BOUNDARY_MERGE_TOLERANCE
    return rule_top <= top + tolerance and rule_bottom >= bottom - tolerance


def _through_columns(rects, col_xs: list[float], row_ys: list[float]) -> tuple[float, ...]:
    """Every x in `col_xs` came from a vertical rule among `rects`."""
    verticals = [rect for rect in rects if _classify_rect(rect) == "vertical"]
    return tuple(x for x in col_xs if _runs_full_height(x, verticals, row_ys[0], row_ys[-1]))


def rects_form_a_grid(rects: list[tuple[float, float, float, float]]) -> bool:
    """True when a set of drawing rects, on their own, describe a real table
    grid (>=MIN_TABLE_ROWS x >=MIN_TABLE_COLS cells) - the same purely-
    geometric row/column-boundary count detect_tables_on_page itself gates
    on, but usable without a caption anchor.

    Lets image_extractor.vector_images_on_page recognize a caption-less
    table fragment as "not a diagram" - e.g. Table 1.1.1.1.(5)'s
    continuation tail, which shares page 12 with Table 1.1.1.1.(6)'s own
    caption and so never becomes a TableRegion of its own (see fill_
    continuation_gaps's docstring) - without attempting the text-to-row
    reconstruction that was reverted there as unreliable: this looks only
    at rects, never at text, so it doesn't run into the prose-vs-row
    ambiguity that sank that earlier attempt.
    """
    row_ys, col_xs = _grid_boundaries(rects, below_y=0.0)
    return len(row_ys) - 1 >= MIN_TABLE_ROWS and len(col_xs) - 1 >= MIN_TABLE_COLS


def _band_index(value: float, boundaries: list[float]) -> int | None:
    for i in range(len(boundaries) - 1):
        if boundaries[i] - BOUNDARY_MERGE_TOLERANCE <= value < boundaries[i + 1]:
            return i
    return None


def _rule_through(x: float, y: float, verticals: list) -> bool:
    return any(
        abs((r[0] + r[2]) / 2 - x) <= BOUNDARY_MERGE_TOLERANCE and r[1] <= y <= r[3]
        for r in verticals
    )


def _ruled_boundaries(pline: PageLine, col_xs: list[float], verticals: list) -> list[float]:
    """The inner column rules that cross the line itself - not a heading's
    span over columns whose rules start below it."""
    x0, y0, x1, y1 = pline.bbox
    inside = (
        x for x in col_xs[1:-1] if x0 + BOUNDARY_MERGE_TOLERANCE < x < x1 - BOUNDARY_MERGE_TOLERANCE
    )
    return [x for x in inside if _rule_through(x, (y0 + y1) / 2, verticals)]


def _tokens(pline: PageLine) -> list[tuple[int, int, float, float]]:
    """Each word's (start, end, x0, x1); inside a span, x is spread evenly
    over its characters."""
    tokens = []
    for start, end, x0, x1 in pline.runs:
        per_char = (x1 - x0) / max(end - start, 1)
        for word in re.finditer(r"\S+", pline.text[start:end]):
            left, right = start + word.start(), start + word.end()
            tokens.append((left, right, x0 + per_char * word.start(), x0 + per_char * word.end()))
    return tokens


def _piece(pline: PageLine, group: list[tuple[int, int, float, float]], left: float) -> PageLine:
    """`left`: the rule the piece was split past - an estimated x can fall
    just short of it, and a piece is filed by where it starts."""
    start, end = group[0][0], group[-1][1]
    styled = pline.styled.between(start, end)
    bbox = (max(group[0][2], left), pline.bbox[1], group[-1][3], pline.bbox[3])
    return PageLine(bbox=bbox, text=styled.text, font=pline.font, emphasis=styled.emphasis)


def _split_at_rules(pline: PageLine, col_xs: list[float], verticals: list) -> list[PageLine]:
    """Table 3.2.3.1.-B sets values of neighbouring narrow columns as one
    line ("46 91"): split where a column rule runs through it."""
    boundaries = _ruled_boundaries(pline, col_xs, verticals)
    tokens = _tokens(pline)
    if not boundaries or not tokens:
        return [pline]
    band = lambda token: sum(x <= (token[2] + token[3]) / 2 for x in boundaries)  # noqa: E731
    edges = [pline.bbox[0], *boundaries]
    return [_piece(pline, list(g), edges[k]) for k, g in itertools.groupby(tokens, key=band)]


def _cell_of(pline: PageLine, row_ys: list[float], col_xs: list[float]):
    # Column by where the line starts, not its centre: a line spanning
    # columns (a full-width heading row with no divider, e.g. Table
    # 9.38.1.1.'s "9.3.1.3. ...") belongs to the column it starts in -
    # where the site files a spanning cell. A line inside one cell starts
    # and centres in the same column either way.
    cy = (pline.bbox[1] + pline.bbox[3]) / 2
    row_i, col_i = _band_index(cy, row_ys), _band_index(pline.bbox[0], col_xs)
    return None if row_i is None or col_i is None else (row_i, col_i)


def _inside(pline: PageLine, outer: tuple[float, float, float, float]) -> bool:
    cx = (pline.bbox[0] + pline.bbox[2]) / 2
    cy = (pline.bbox[1] + pline.bbox[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _file_pieces(cells: dict, pieces: list[PageLine], row_ys, col_xs) -> bool:
    filed = False
    for piece in pieces:
        key = _cell_of(piece, row_ys, col_xs)
        if key is not None:
            cells.setdefault(key, []).append(piece)
            filed = True
    return filed


def _assign_lines_to_cells(
    lines: list[PageLine], row_ys: list[float], col_xs: list[float], rects=()
) -> tuple[dict[tuple[int, int], list[PageLine]], set[int]]:
    cells: dict[tuple[int, int], list[PageLine]] = {}
    consumed = set()
    outer = (col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    verticals = _rules_of_kind(list(rects), "vertical")
    for i, pline in enumerate(lines):
        if not _inside(pline, outer):
            continue
        if _file_pieces(cells, _split_at_rules(pline, col_xs, verticals), row_ys, col_xs):
            consumed.add(i)
    return cells, consumed


def _rule_across(rules: list, y: float, x0: float, x1: float) -> bool:
    """Whether horizontal rules at row boundary `y` cover at least half of
    the column [x0, x1] - the PDF draws its row rules one column at a time."""
    at_y = [r for r in rules if abs((r[1] + r[3]) / 2 - y) <= BOUNDARY_MERGE_TOLERANCE]
    covered = sum(max(0.0, min(r[2], x1) - max(r[0], x0)) for r in at_y)
    return covered >= (x1 - x0) / 2


def _fold_column(cell_lines: dict, folded: dict, col: int, grid) -> None:
    row_ys, col_xs, rules = grid
    first = 0
    for row in range(len(row_ys) - 1):
        if row and _rule_across(rules, row_ys[row], col_xs[col], col_xs[col + 1]):
            first = row
        folded.setdefault((first, col), []).extend(cell_lines.get((row, col), []))


def _fold_row_spans(
    cell_lines: dict[tuple[int, int], list[PageLine]],
    row_ys: list[float],
    col_xs: list[float],
    rects: list[tuple[float, float, float, float]],
) -> dict[tuple[int, int], list[PageLine]]:
    """Moves a cell spanning several rows - no rule between them across its
    column - into the first of them, leaving the rest empty, as the site does.
    The PDF centres such a cell's text vertically (Spec Table 2's "140"),
    so its lines land in whichever row holds the middle."""
    rules = [r for r in rects if _classify_rect(r) == "horizontal"]
    folded: dict[tuple[int, int], list[PageLine]] = {}
    for col in range(len(col_xs) - 1):
        _fold_column(cell_lines, folded, col, (row_ys, col_xs, rules))
    return {key: lines for key, lines in folded.items() if lines}


def _union_bbox(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _cell_bbox(in_cell: list[PageLine], fallback: BBox) -> BBox:
    if not in_cell:
        return fallback
    bbox = BBox(*in_cell[0].bbox)
    for pline in in_cell[1:]:
        bbox = _union_bbox(bbox, BBox(*pline.bbox))
    return bbox


def _cell_node(
    row_citation: str, col_i: int, in_cell: list[PageLine], fallback: BBox, page: int
) -> Node:
    ordered = sorted(in_cell, key=lambda ln: ln.bbox[1])
    content = StyledText("")
    for pline in ordered:
        content = content.join(pline.styled)
    return Node(
        type="Cell",
        identifier=f"Col{col_i + 1}",
        citation=f"{row_citation}-Col{col_i + 1}",
        title="",
        content=content.text,
        emphasis=list(content.emphasis),
        page=page,
        end_page=page,
        bbox=_cell_bbox(in_cell, fallback),
    )


def _row_node(table_citation: str, row_i: int, page: int, cells: list[Node]) -> Node:
    bbox = cells[0].bbox
    for cell in cells[1:]:
        bbox = _union_bbox(bbox, cell.bbox)
    return Node(
        type="Row",
        identifier=f"Row{row_i + 1}",
        citation=f"{table_citation}-Row{row_i + 1}",
        title="",
        page=page,
        end_page=page,
        bbox=bbox,
        children=cells,
    )


def _forming_part_of_above(lines: list[PageLine], caption_idx: int, grid_top_y: float):
    for i in range(caption_idx + 1, len(lines)):
        pline = lines[i]
        if pline.bbox[1] >= grid_top_y:
            break
        match = RE_FORMING_PART_OF.match(pline.text)
        if match:
            return i, (match.group(1), match.group(2))
    return None, None


def _has_bottom_border(rects, row_bottom_y: float) -> bool:
    return any(
        _classify_rect(r) == "horizontal"
        and abs((r[1] + r[3]) / 2 - row_bottom_y) <= BOUNDARY_MERGE_TOLERANCE
        for r in rects
    )


def _build_rows(
    row_ys: list[float],
    col_xs: list[float],
    cell_lines: dict[tuple[int, int], list[PageLine]],
    table_citation: str,
    page_number: int,
) -> list[Node]:
    rows = []
    for row_i in range(len(row_ys) - 1):
        cells = []
        for col_i in range(len(col_xs) - 1):
            in_cell = cell_lines.get((row_i, col_i), [])
            fallback = BBox(col_xs[col_i], row_ys[row_i], col_xs[col_i + 1], row_ys[row_i + 1])
            row_citation = f"{table_citation}-Row{row_i + 1}"
            cells.append(_cell_node(row_citation, col_i, in_cell, fallback, page_number))
        rows.append(_row_node(table_citation, row_i, page_number, cells))
    return rows


def _consume_table_title(
    lines: list[PageLine], caption_idx: int, grid_top_y: float
) -> tuple[str, int]:
    """Mirrors tree_builder._consume_caption_title's own bold-font-gated,
    up-to-3-line reading of a caption's descriptive title - but bounded above
    by the grid's own top edge, since a Table caption's title (when present)
    sits between the caption trigger line and the grid, in the same bold
    caption font as the anchor line itself.

    tree_builder's own _open_caption/_consume_caption_title never runs for
    this line: the caption trigger line is always in build_table_region's
    consumed set below, so tree_builder._process_page skips it before ever
    reaching the classify_caption_line check that would call _open_caption.
    table_extractor.py therefore owns this title's text AND its line
    indices exclusively - returning next_idx lets the caller add
    range(caption_idx + 1, next_idx) to consumed, so this text is never
    also picked up by _append_to_current_article as body content of
    whatever Sentence/Clause/Subclause happens to be open on the page.
    """
    caption_font = lines[caption_idx].font
    parts = []
    idx = caption_idx + 1
    while idx < len(lines) and len(parts) < 3:
        pline = lines[idx]
        if pline.bbox[1] >= grid_top_y or not is_caption_title_font(pline.font, caption_font):
            break
        parts.append(pline.text)
        idx += 1
    return " ".join(parts).strip(), idx


def build_table_region(
    anchor: TableAnchor,
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    page_number: int,
    above_y: float | None = None,
) -> TableRegion | None:
    """`above_y`: where the next table's caption starts on this page - this
    table's grid stops there, rather than taking every ruled line below its
    own caption (which merged stacked tables and swallowed the text between
    them, e.g. the Article 4.1.8.6. heading on page 543)."""
    caption_bottom = lines[anchor.caption_line_idx].bbox[3]
    row_ys, col_xs = _grid_boundaries(drawing_rects, below_y=caption_bottom, above_y=above_y)
    if len(row_ys) - 1 < MIN_ANCHOR_TABLE_ROWS or len(col_xs) - 1 < MIN_TABLE_COLS:
        return None

    title, title_end_idx = _consume_table_title(lines, anchor.caption_line_idx, row_ys[0])
    forming_idx, forming_part_of = _forming_part_of_above(lines, anchor.caption_line_idx, row_ys[0])
    caption_lines = set(range(anchor.caption_line_idx, title_end_idx))
    if forming_idx is not None:
        caption_lines.add(forming_idx)
    grid = _Grid(row_ys, col_xs, drawing_rects)
    caption = (title, forming_part_of, caption_lines)
    return _region_from_grid(anchor, lines, grid, page_number, caption)


@dataclass
class _Grid:
    row_ys: list[float]
    col_xs: list[float]
    drawing_rects: list[tuple[float, float, float, float]]


def _region_from_grid(
    anchor: TableAnchor, lines: list[PageLine], grid: _Grid, page_number: int, caption
) -> TableRegion:
    """`caption`: (title, forming_part_of, the caption's own line indices on
    this page) - all empty for a grid whose caption is on the page before."""
    title, forming_part_of, caption_lines = caption
    row_ys, col_xs = grid.row_ys, grid.col_xs
    cell_lines, consumed = _assign_lines_to_cells(lines, row_ys, col_xs, grid.drawing_rects)
    cell_lines = _fold_row_spans(cell_lines, row_ys, col_xs, grid.drawing_rects)
    table_citation = f"Table:{anchor.identifier}"
    outer_bbox = BBox(col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    table_node = Node(
        type="Table",
        identifier=anchor.identifier,
        citation=table_citation,
        title=title,
        page=page_number,
        end_page=page_number,
        bbox=outer_bbox,
        children=_build_rows(row_ys, col_xs, cell_lines, table_citation, page_number),
    )
    return TableRegion(
        anchor=anchor,
        table_node=table_node,
        forming_part_of=forming_part_of,
        consumed_line_indices=consumed | caption_lines,
        has_bottom_border=_has_bottom_border(grid.drawing_rects, row_ys[-1]),
        outer_bbox=outer_bbox,
        col_xs=tuple(col_xs),
        through_xs=_through_columns(grid.drawing_rects, col_xs, row_ys),
    )


def build_orphaned_region(
    anchor: TableAnchor,
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    page_number: int,
    forming_part_of: tuple[str, str] | None = None,
) -> TableRegion | None:
    """The grid of a table whose caption ended the previous page (e.g.
    "Table 9.24.2.5." on page 926, its grid atop page 927): the ruled lines
    at the top of this page, down to this page's own first caption. Its
    title stays with its caption, which tree_builder records;
    `forming_part_of` is read from under that caption."""
    own_anchors = find_table_anchors(lines, page_number - 1)
    above_y = lines[own_anchors[0].caption_line_idx].bbox[1] if own_anchors else None
    row_ys, col_xs = _grid_boundaries(drawing_rects, below_y=0.0, above_y=above_y)
    if len(row_ys) - 1 < MIN_ANCHOR_TABLE_ROWS or len(col_xs) - 1 < MIN_TABLE_COLS:
        return None
    grid = _Grid(row_ys, col_xs, drawing_rects)
    return _region_from_grid(anchor, lines, grid, page_number, ("", forming_part_of, set()))


def detect_tables_on_page(
    lines: list[PageLine], drawing_rects: list[tuple[float, float, float, float]], page_number: int
) -> list[TableRegion]:
    anchors = find_table_anchors(lines, page_number - 1)
    caption_tops = [lines[a.caption_line_idx].bbox[1] for a in anchors]
    regions = []
    for i, anchor in enumerate(anchors):
        above_y = caption_tops[i + 1] if i + 1 < len(anchors) else None
        region = build_table_region(anchor, lines, drawing_rects, page_number, above_y)
        if region is not None:
            regions.append(region)
    return regions


def _renumber_row(table_citation: str, row: Node, row_i: int) -> None:
    row.identifier = f"Row{row_i + 1}"
    row.citation = f"{table_citation}-{row.identifier}"
    for cell in row.children:
        cell.citation = f"{row.citation}-{cell.identifier}"


def _column_count(region: TableRegion) -> int:
    """Its last row's - once a header-only page has taken on a body of
    other columns, the next page carries on the body."""
    rows = region.table_node.children
    return len(rows[-1].children) if rows else 0


def _all_bold(cell: Node) -> bool:
    signature = StyledText.from_json(cell.content, cell.emphasis).signature()
    return all("b" in style for char, style in signature if char.isalnum())


def _only_header(region: TableRegion) -> bool:
    """Whether the table so far is only its bold header - all its caption's
    page had room for (Table 9.23.13.7.-A, page 892). The header's columns
    need not be the body's: its spanning headings drew fewer rules."""
    filled = [c for row in region.table_node.children for c in row.children if c.content.strip()]
    return bool(filled) and all(_all_bold(cell) for cell in filled)


def _same_x_range(a: BBox, b: BBox) -> bool:
    return (
        abs(a.x0 - b.x0) <= BOUNDARY_MERGE_TOLERANCE
        and abs(a.x1 - b.x1) <= BOUNDARY_MERGE_TOLERANCE
    )


def _splits_columns(prev_xs: tuple[float, ...], next_xs: tuple[float, ...]) -> bool:
    """Whether the next page keeps every column rule of the page before and
    only adds rules - Table 9.23.13.7.-D's page 904 splits page 903's factor
    column in two. `next_xs` are the rules running the next grid's full
    height: on page 1425 -D's middle rule stops under its last row, over
    another table whose rules happen to include -D's."""
    tolerance = BOUNDARY_MERGE_TOLERANCE
    return bool(prev_xs) and all(any(abs(p - n) <= tolerance for n in next_xs) for p in prev_xs)


def _columns_carry_on(pending: TableRegion, col_count: int, through_xs: tuple[float, ...]) -> bool:
    return (
        col_count == _column_count(pending)
        or _only_header(pending)
        or _splits_columns(pending.col_xs, through_xs)
    )


def _same_shape(prev: TableRegion, next_region: TableRegion) -> bool:
    same_columns = _columns_carry_on(prev, _column_count(next_region), next_region.through_xs)
    return _same_x_range(prev.outer_bbox, next_region.outer_bbox) and same_columns


def _continues_previous(prev: TableRegion, next_region: TableRegion) -> bool:
    # A different caption is a different table, however alike its shape.
    same_table = prev.table_node.identifier == next_region.table_node.identifier
    return same_table and not prev.has_bottom_border and _same_shape(prev, next_region)


def _filled_columns(row: Node) -> list[int]:
    return [i for i, cell in enumerate(row.children) if cell.content.strip()]


def _is_page_split_tail(last: Node, first: Node) -> bool:
    """Whether a continuation page's first row is really the rest of the
    previous page's last row, cut by the page break: one filled cell, not in
    the first column, continuing a cell the last row filled - while the last
    row also filled a column to its right that this one leaves empty (e.g.
    wall W6i's ratings). A real new row under a spanning cell (B.9.38.1.1)
    has one filled cell too, but nothing to its right in the row above."""
    filled = _filled_columns(first)
    if len(filled) != 1 or filled[0] == 0 or len(first.children) != len(last.children):
        return False
    last_filled = _filled_columns(last)
    return filled[0] in last_filled and last_filled[-1] > filled[0]


def _join_cell(cell: Node, tail: Node) -> None:
    joined = StyledText.from_json(cell.content, cell.emphasis).join(
        StyledText.from_json(tail.content, tail.emphasis)
    )
    cell.content = joined.text
    cell.emphasis = list(joined.emphasis)
    cell.end_page = tail.end_page


def _rejoin_page_split_row(pending: TableRegion, region: TableRegion) -> list[Node]:
    """The continuation page's rows, minus a first row that was only the
    tail of the previous page's last row - folded back into that row."""
    rows = region.table_node.children
    if not (pending.table_node.children and rows):
        return rows
    last, first = pending.table_node.children[-1], rows[0]
    if not _is_page_split_tail(last, first):
        return rows
    col = _filled_columns(first)[0]
    _join_cell(last.children[col], first.children[col])
    last.end_page = first.end_page
    return rows[1:]


def _merge_into(pending: TableRegion, region: TableRegion) -> None:
    table_citation = pending.table_node.citation
    start = len(pending.table_node.children)
    rows = _rejoin_page_split_row(pending, region)
    for i, row in enumerate(rows):
        _renumber_row(table_citation, row, start + i)
    pending.table_node.children.extend(rows)
    pending.table_node.end_page = region.table_node.page
    pending.has_bottom_border = region.has_bottom_border


def _accumulate_region(
    stitched: list[TableRegion], pending: TableRegion | None, region: TableRegion
) -> TableRegion:
    if pending is not None and _continues_previous(pending, region):
        _merge_into(pending, region)
        return pending
    if pending is not None:
        stitched.append(pending)
    return region


def stitch_continuations(regions_by_page: list[list[TableRegion]]) -> list[TableRegion]:
    stitched: list[TableRegion] = []
    pending: TableRegion | None = None
    for region in itertools.chain.from_iterable(regions_by_page):
        pending = _accumulate_region(stitched, pending, region)
    if pending is not None:
        stitched.append(pending)
    return stitched


def _citation_index(volume: Node) -> dict[str, Node]:
    index = {}

    def walk(node: Node) -> None:
        index[node.citation] = node
        for child in node.children:
            walk(child)

    walk(volume)
    return index


def _latest_division_at_or_before(divisions: list[Node], page: int) -> Node | None:
    candidates = [d for d in divisions if d.page <= page]
    if candidates:
        return max(candidates, key=lambda d: d.page)
    return divisions[0] if divisions else None


def _division_for_page(volume: Node, page: int) -> str:
    divisions = [c for c in volume.children if c.type == "Division"]
    chosen = _latest_division_at_or_before(divisions, page)
    return chosen.identifier if chosen else ""


def resolve_owner_citation(
    region: TableRegion, division: str, index: dict[str, Node], volume: Node
) -> str:
    direct = index.get(f"{division}-{region.anchor.identifier}")
    if direct is not None:
        return direct.citation
    if region.forming_part_of is not None:
        _, ref = region.forming_part_of
        by_ref = index.get(f"{division}-{ref}") or index.get(ref)
        if by_ref is not None:
            return by_ref.citation
    return assign_owner(region.table_node, volume)


def _matching_caption(region: TableRegion, captions: list[Caption]) -> Caption | None:
    return next(
        (c for c in captions if c.kind == "Table" and c.identifier == region.anchor.identifier),
        None,
    )


def _own_forming_part_of_reference(lines: list[PageLine], grid_top_y: float) -> str | None:
    """Bounded above the candidate's own grid top, mirroring
    _forming_part_of_above's bound between an anchor's caption and its
    grid.

    CORRECTED after a factual misdiagnosis in an earlier round: that round
    left this scan unbounded, reasoning (wrongly) that real page 926's
    detected grid spanned all the way down to a "Forming Part of Sentence
    9.24.2.5.(1)" line found on that page. Direct re-inspection shows this
    was false - page 926's real, genuine-continuation grid runs only
    y=72.36-243.12 (10 real data rows of Table 9.24.2.1., e.g. "600"/"2.7",
    "300"/"4.4", "32 x 64"/"400"/"4.0", matching Table 9.24.2.1.'s own
    column count and shape exactly), while that forming-part-of line sits
    at y=692 - hundreds of points below the grid's own bottom, part of an
    entirely unrelated later table (9.24.2.5.) introduced by ordinary body
    prose ("9.24.2.5. Size and Spacing of Studs in Exterior Walls...")
    further down the SAME page. An unbounded scan wrongly let that distant,
    unrelated line reject page 926 as a false positive, when it is in fact
    a genuine continuation - the exact opposite of a fix. Bounding the scan
    to strictly above the grid's own top (where this document's genuine
    continuation pages have nothing at all, and a genuinely new table's own
    caption/title/forming-part-of block - see page 835 in
    _has_leading_title_block, or pages 170/185's own captions - does sit)
    is correct after all.
    """
    for pline in lines:
        if pline.bbox[1] >= grid_top_y:
            continue
        match = RE_FORMING_PART_OF.match(pline.text)
        if match:
            return match.group(2).strip()
    return None


def _forming_part_of_conflicts(
    lines: list[PageLine], pending: TableRegion, grid_top_y: float
) -> bool:
    """A genuinely new, unrelated table can coincidentally share `pending`'s
    column count and x-range (this document uses consistent margins across
    all its tables) even on a page where detect_tables_on_page found no
    "Table X" caption trigger for it - confirmed on 3 real pages (170, 185,
    835), each absorbed as fake continuation rows of a preceding, unrelated
    table before this guard existed. Such a page's own "Forming part of
    ..." line, when present, points somewhere else - a cheap, strong
    signal this is not really a continuation of `pending`, even when the
    shape happens to match.

    (Page 926, once believed to be a 4th such case, is NOT one - see
    _own_forming_part_of_reference's docstring for the correction; it is a
    genuine continuation, correctly accepted once this scan is properly
    bounded above the candidate's own grid.)

    Compares reference-to-reference whenever possible: `pending.forming_
    part_of` is now propagated through the whole continuation chain (see
    build_continuation_region), never reset to None, so the identifier
    fallback below is reached only when the ORIGINAL anchored table
    genuinely never had a forming-part-of line at all - not, as an earlier
    round of this fix relied on by accident, whenever `pending` happened to
    be a synthesized region. Comparing a table's own identifier against a
    forming-part-of reference is a different namespace in general (e.g. a
    hypothetical identifier "X.Y.Z." vs. a reference "X.Y.Z.(1)"); it is
    used here only as a last-resort, best-effort signal when no real
    reference is available to compare against.
    """
    candidate_ref = _own_forming_part_of_reference(lines, grid_top_y)
    if candidate_ref is None:
        return False
    expected_ref = (
        pending.forming_part_of[1] if pending.forming_part_of else pending.table_node.identifier
    )
    return candidate_ref != expected_ref


def _has_leading_title_block(lines: list[PageLine], grid_top_y: float) -> bool:
    """A true continuation page never introduces a new descriptive title
    above its grid - there is nothing to title, since it is a continuation,
    not an introduction. Reuses the same bold-caption-font signal
    _consume_table_title uses to read a genuine table's own title on an
    anchored page, to catch a case _forming_part_of_conflicts alone cannot:
    sibling table families (e.g. Table 9.15.4.5.-A/-B/-C) that all share
    the SAME "Forming part of Sentence 9.15.4.5.(2)" reference, so
    reference equality alone can't tell them apart. Confirmed on the real
    document: page 835's Table 9.15.4.5.-C has its own bold-caption-font
    descriptive title ("Vertical Reinforcement for 240 mm Flat Insulating
    Concrete Form Founda...") sitting directly above its grid, even though
    its forming-part-of reference agrees with the preceding, unrelated
    Table 9.15.4.5.-B.

    Walks backward from the line immediately preceding the grid: a
    "Forming part of ..." line is skipped (an expected, legitimate
    non-title element that can sit directly above a REAL table's grid
    too), and a contiguous run of caption-font lines immediately touching
    the grid (through any such skipped line) counts as a title block: the
    walk stops at the first line that is neither.
    """
    above = [pline for pline in lines if pline.bbox[1] < grid_top_y]
    found_title = False
    for pline in reversed(above):
        if RE_FORMING_PART_OF.match(pline.text):
            continue
        if not is_caption_font(pline.font):
            break
        found_title = True
    return found_title


def _continuation_shape_matches(
    outer_bbox: BBox, col_count: int, through_xs: tuple[float, ...], pending: TableRegion
) -> bool:
    same_columns = _columns_carry_on(pending, col_count, through_xs)
    return same_columns and _same_x_range(outer_bbox, pending.outer_bbox)


def build_continuation_region(
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    page_number: int,
    pending: TableRegion,
) -> TableRegion | None:
    """Detects a continuation page's grid WITHOUT a caption anchor: a page
    whose own detect_tables_on_page pass found nothing (no "Table X" line)
    can still hold rows of a still-open (no bottom border) table from a
    preceding page. Matched by column count and x-range against `pending`,
    guarded against a coincidental shape match to a genuinely different
    table by _forming_part_of_conflicts and _has_leading_title_block - two
    complementary, independent signals, since neither alone rejects every
    known real-document false positive (see each function's own docstring).
    """
    row_ys, col_xs = _grid_boundaries(drawing_rects, below_y=0.0)
    if len(row_ys) - 1 < 1 or len(col_xs) - 1 < MIN_TABLE_COLS:
        return None
    outer_bbox = BBox(col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    through_xs = _through_columns(drawing_rects, col_xs, row_ys)
    same_shape = _continuation_shape_matches(outer_bbox, len(col_xs) - 1, through_xs, pending)
    rejected = (
        not same_shape
        or _forming_part_of_conflicts(lines, pending, row_ys[0])
        or _has_leading_title_block(lines, row_ys[0])
    )
    if rejected:
        return None

    cell_lines, consumed = _assign_lines_to_cells(lines, row_ys, col_xs, drawing_rects)
    cell_lines = _fold_row_spans(cell_lines, row_ys, col_xs, drawing_rects)
    rows = _build_rows(row_ys, col_xs, cell_lines, pending.table_node.citation, page_number)
    table_node = Node(
        type="Table",
        identifier=pending.table_node.identifier,
        citation=pending.table_node.citation,
        title="",
        page=page_number,
        end_page=page_number,
        bbox=outer_bbox,
        children=rows,
    )
    return TableRegion(
        anchor=pending.anchor,
        table_node=table_node,
        # Propagated, not reset to None: the ORIGINAL anchored table's own
        # forming_part_of carries forward through the whole continuation
        # chain, so _forming_part_of_conflicts always compares a real
        # reference against a real reference at every step, never falling
        # back to comparing a table identifier against a reference (a
        # different namespace in general - see that function's docstring).
        forming_part_of=pending.forming_part_of,
        consumed_line_indices=consumed,
        has_bottom_border=_has_bottom_border(drawing_rects, row_ys[-1]),
        outer_bbox=outer_bbox,
        col_xs=tuple(col_xs),
        through_xs=through_xs,
    )


def _next_pending(regions: list[TableRegion]) -> TableRegion | None:
    """Returns the last region on a page as the shape reference to check
    against the following (caption-less) page, regardless of has_bottom_
    border.

    Deviates from the brief's own illustrative code, which gated this on
    `not regions[-1].has_bottom_border` ("pending" = "still open"). Real-PDF
    verification (Step 4) showed that assumption false for this document:
    Table 1.1.1.1.(5)'s own page-8 fragment has a genuine closing bottom
    border - the source PDF redraws a fully-bordered box per page for
    whatever rows fit, even mid-table, so has_bottom_border reflects only
    "this page's box is visually closed," never "the logical table ends
    here." Gating on it made continuation detection never fire for the
    exact case this task exists to fix.

    column-count-and-x-range matching in build_continuation_region is left
    as the sole discriminator, exactly as the brief itself already
    describes it - fill_continuation_gaps only ever calls it on a page
    that produced zero of its own anchor-detected regions, so a page with
    a genuine new "Table X" caption (even one sharing the same column
    count/x-range, confirmed on page 12's Table 1.1.1.1.(6) here) is never
    mistaken for a continuation: it already has its own region and short-
    circuits back to the `if regions:` branch above.
    """
    return regions[-1] if regions else None


def _fill_one_gap(
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    page_number: int,
    pending: TableRegion,
) -> TableRegion | None:
    synthesized = build_continuation_region(lines, drawing_rects, page_number, pending)
    if synthesized is not None:
        # Ground-truth correction: `pending` genuinely continues (we just
        # matched its shape on the very next page), so whatever
        # has_bottom_border its OWN page-local grid computed was a false
        # signal - see build_continuation_region's docstring and
        # _next_pending's comment for why. stitch_continuations/
        # _continues_previous stay untouched; this only corrects the data
        # they read, so they merge these rows using their own existing,
        # unmodified rule.
        pending.has_bottom_border = False
    return synthesized


def _preceding_page_has_orphaned_anchor(
    lines: list[PageLine], regions: list[TableRegion], page_index: int
) -> bool:
    """True when the immediately preceding page introduced a table via its
    own "Table X" caption trigger, but that caption's own grid did not fit
    on that page (find_table_anchors found MORE anchors there than detect_
    tables_on_page produced regions for - i.e. build_table_region returned
    None for at least one of them).

    Confirmed real case (page 916): page 915 carries TWO anchors, "Table
    9.23.13.11.-C" and "Table 9.23.13.11.-D", but only ONE region (C's
    grid fit on page 915; D's caption, title, and header row are there too,
    but D's actual data grid did not fit and spills onto the next page).
    Page 916 itself then carries only D's bare data grid - no caption, no
    title, no forming-part-of line of its own, so neither
    _forming_part_of_conflicts nor _has_leading_title_block (which only
    ever inspect the CANDIDATE page) has anything to see there. When this
    is true, the CURRENT (candidate) page is that orphaned table's own
    real first grid - not a continuation of whatever else was pending -
    regardless of whether its shape happens to match.
    """
    anchors = find_table_anchors(lines, page_index)
    return len(anchors) > len(regions)


def _orphaned_anchor(lines: list[PageLine], regions: list[TableRegion], page_index: int):
    """The page's last caption, when it got no grid of its own there - its
    grid, if any, is on the next page."""
    anchors = find_table_anchors(lines, page_index)
    if not anchors or any(r.anchor == anchors[-1] for r in regions):
        return None
    return anchors[-1]


def _orphaned_region(
    all_lines: list[list[PageLine]],
    all_drawing_rects: list[list[tuple[float, float, float, float]]],
    regions_by_page: list[list[TableRegion]],
    page_index: int,
) -> TableRegion | None:
    if page_index == 0:
        return None
    prev = page_index - 1
    anchor = _orphaned_anchor(all_lines[prev], regions_by_page[prev], prev)
    if anchor is None:
        return None
    _, forming_part_of = _forming_part_of_above(
        all_lines[prev], anchor.caption_line_idx, grid_top_y=float("inf")
    )
    return build_orphaned_region(
        anchor,
        all_lines[page_index],
        all_drawing_rects[page_index],
        page_index + 1,
        forming_part_of,
    )


def _handle_gap_page(
    all_lines: list[list[PageLine]],
    all_drawing_rects: list[list[tuple[float, float, float, float]]],
    regions_by_page: list[list[TableRegion]],
    filled: list[list[TableRegion]],
    page_index: int,
    pending: TableRegion | None,
) -> TableRegion | None:
    """Processes one caption-less candidate page, mutating filled[page_index]
    in place, and returns the pending state to carry into the next page.
    """
    if pending is None:
        return None
    if page_index > 0 and _preceding_page_has_orphaned_anchor(
        all_lines[page_index - 1], regions_by_page[page_index - 1], page_index - 1
    ):
        filled[page_index] = []
        return None
    synthesized = _fill_one_gap(
        all_lines[page_index], all_drawing_rects[page_index], page_index + 1, pending
    )
    filled[page_index] = [synthesized] if synthesized else []
    return _next_pending(filled[page_index])


def _within_column_reach(rects: list) -> list:
    """Drops the rules below where the column rules end."""
    verticals = _rules_of_kind(rects, "vertical")
    if not verticals:
        return rects
    bottom = max(rect[3] for rect in verticals) + BOUNDARY_MERGE_TOLERANCE
    return [rect for rect in rects if rect[1] <= bottom]


def _add_tail_above_caption(
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    regions: list[TableRegion],
    pending: TableRegion,
) -> None:
    """A table can end at the top of a page that opens the next table
    further down (9.23.4.2.-K's last rows over 9.23.4.2.-L's caption, page
    1364). Only the lines before that caption and the rules ending above
    it are read, with every continuation guard, so the next table's own
    text never joins the grid; prose there forms no grid of its own, and a
    rule under the tail that no column reaches (page 12's, above
    1.1.1.1.(6)'s caption) bounds no row."""
    caption_idx = regions[0].anchor.caption_line_idx
    caption_top = lines[caption_idx].bbox[1]
    rects_above = _within_column_reach([r for r in drawing_rects if r[3] <= caption_top])
    page_number = regions[0].table_node.page
    tail = _fill_one_gap(lines[:caption_idx], rects_above, page_number, pending)
    if tail is not None:
        regions.insert(0, tail)


def _add_leading_region(
    all_lines: list[list[PageLine]],
    all_drawing_rects: list[list[tuple[float, float, float, float]]],
    page_regions: tuple[list[list[TableRegion]], list[TableRegion]],
    page_index: int,
    pending: TableRegion | None,
) -> None:
    """Puts the grid atop a page, if it belongs to a table from the page
    before, first among `regions` (this page's regions): an orphaned
    caption's grid, else the tail of `pending`."""
    regions_by_page, regions = page_regions
    orphaned = _orphaned_region(all_lines, all_drawing_rects, regions_by_page, page_index)
    if orphaned is not None:
        regions.insert(0, orphaned)
    elif regions and pending is not None:
        lines, rects = all_lines[page_index], all_drawing_rects[page_index]
        _add_tail_above_caption(lines, rects, regions, pending)


def fill_continuation_gaps(
    all_lines: list[list[PageLine]],
    all_drawing_rects: list[list[tuple[float, float, float, float]]],
    regions_by_page: list[list[TableRegion]],
) -> list[list[TableRegion]]:
    """Sequential pass, run AFTER all pages are extracted: fills in the
    previously-empty page slots left by a multi-page table's continuation
    pages (which have no caption trigger line, so detect_tables_on_page
    finds nothing there). The synthesized region is inserted straight into
    regions_by_page, and the existing stitch_continuations machinery
    consumes it unchanged - it doesn't know or care whether a region came
    from a caption anchor or from this continuation synthesis.

    NOTE - not a pure "list in, list out" function despite the signature:
    when a continuation is confirmed, it also mutates the PRECEDING
    TableRegion object it was given in `regions_by_page` in place (via
    _fill_one_gap's `pending.has_bottom_border = False` correction - see
    that function's own docstring for why). Callers that keep their own
    reference to the `regions_by_page` argument after calling this will see
    that correction reflected in those same objects too.

    A continuation's tail that shares a page with the NEXT table's caption
    (Table 1.1.1.1.(5)'s last rows above 1.1.1.1.(6)'s caption, page 12) is
    read by _add_tail_above_caption. An earlier attempt at that took
    Sentence 1.1.1.1.(6)'s prose, sitting in the same gap, for rows (see
    task-14-report.md); the tail is now bounded to the ruled grid the
    column rules reach, above the caption.

    Also rejects a candidate page outright, without even attempting a
    shape/forming-part-of/title-block match, when the immediately
    preceding page holds an anchor that produced no region of its own -
    see _preceding_page_has_orphaned_anchor.
    """
    filled = [list(regions) for regions in regions_by_page]
    pending: TableRegion | None = None
    for page_index, regions in enumerate(filled):
        _add_leading_region(
            all_lines, all_drawing_rects, (regions_by_page, regions), page_index, pending
        )
        if regions:
            pending = _next_pending(regions)
            continue
        pending = _handle_gap_page(
            all_lines, all_drawing_rects, regions_by_page, filled, page_index, pending
        )
    return filled


def _register_table_citation(
    table_node: Node, index: dict[str, Node], seen_citations: set[str]
) -> None:
    """Raises rather than silently overwriting the index when two regions in
    the SAME attach_tables() call resolve to the same citation - a currently-
    latent x-range-drift risk on long continuation chains (see stitch_
    continuations) that would otherwise hide a duplicate table by keeping
    only the last one written.

    KNOWN LIMITATION, deliberately not closed: `seen_citations` only tracks
    citations registered during THIS call, so a collision against a citation
    already present in `index` from a citation BEFORE this call started
    (e.g. attach_tables() invoked more than once against the same tree)
    still silently overwrites via the `index[citation] = table_node` line
    below. Widening the check to the whole `index` would also reject
    test_attach_tables_leaves_title_empty_when_no_caption_matches's
    deliberate two-separate-calls-same-identifier path, which is not a bug -
    each attach_tables() call is otherwise independent. In the real
    pipeline, attach_tables() is only ever called once per document build
    (see build_mo_toc.build_document), so this cross-call gap is currently
    unreachable in practice; left as a documented limitation rather than a
    fix that would require redesigning how repeated calls are meant to
    compose.
    """
    citation = table_node.citation
    if citation in seen_citations:
        raise ValueError(
            f"Duplicate table citation {citation!r}: two TableRegions in the "
            "same attach_tables() call resolved to the same citation."
        )
    seen_citations.add(citation)
    index[citation] = table_node


def attach_tables(volume: Node, regions: list[TableRegion], captions: list[Caption] = ()) -> None:
    index = _citation_index(volume)
    seen_citations: set[str] = set()
    for region in regions:
        division = _division_for_page(volume, region.table_node.page)
        owner_citation = resolve_owner_citation(region, division, index, volume)
        owner = index[owner_citation]
        _register_table_citation(region.table_node, index, seen_citations)
        owner.children.append(region.table_node)
        caption = _matching_caption(region, captions)
        if caption is not None and caption.title:
            region.table_node.title = caption.title
