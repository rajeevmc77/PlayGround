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
from mo_toc.parsing.heading_rules import classify_caption_line, is_caption_font
from mo_toc.parsing.image_matcher import assign_owner
from mo_toc.parsing.pdf_source import PageLine

RE_FORMING_PART_OF = re.compile(
    r"^Forming [Pp]art of (Sentence|Clause|Subclause|Article|Section|Subsection)\s+(.+?)\.?$"
)

LINE_THICKNESS_MAX = 2.0  # pt; a gridline rect's thin dimension
BOUNDARY_MERGE_TOLERANCE = 2.0  # pt; nearby edges from adjacent segments are one boundary
MIN_TABLE_ROWS = 2  # header + at least one data row
MIN_TABLE_COLS = 2


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


def find_table_anchors(lines: list[PageLine], page_index: int) -> list[TableAnchor]:
    anchors = []
    for idx, pline in enumerate(lines):
        cap_match = classify_caption_line(pline.text, pline.font)
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


def _grid_boundaries(
    rects: list[tuple[float, float, float, float]], below_y: float
) -> tuple[list[float], list[float]]:
    row_ys, col_xs = [], []
    for rect in rects:
        x0, y0, x1, y1 = rect
        if y0 < below_y - BOUNDARY_MERGE_TOLERANCE:
            continue
        kind = _classify_rect(rect)
        if kind == "horizontal":
            row_ys.append((y0 + y1) / 2)
        elif kind == "vertical":
            col_xs.append((x0 + x1) / 2)
    return _merge_boundaries(row_ys), _merge_boundaries(col_xs)


def _band_index(value: float, boundaries: list[float]) -> int | None:
    for i in range(len(boundaries) - 1):
        if boundaries[i] - BOUNDARY_MERGE_TOLERANCE <= value < boundaries[i + 1]:
            return i
    return None


def _assign_lines_to_cells(
    lines: list[PageLine], row_ys: list[float], col_xs: list[float]
) -> tuple[dict[tuple[int, int], list[PageLine]], set[int]]:
    cells: dict[tuple[int, int], list[PageLine]] = {}
    consumed = set()
    outer = (col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    for i, pline in enumerate(lines):
        cx = (pline.bbox[0] + pline.bbox[2]) / 2
        cy = (pline.bbox[1] + pline.bbox[3]) / 2
        if not (outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]):
            continue
        row_i, col_i = _band_index(cy, row_ys), _band_index(cx, col_xs)
        if row_i is None or col_i is None:
            continue
        cells.setdefault((row_i, col_i), []).append(pline)
        consumed.add(i)
    return cells, consumed


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
    content = " ".join(ln.text for ln in ordered).strip()
    return Node(
        type="Cell",
        identifier=f"Col{col_i + 1}",
        citation=f"{row_citation}-Col{col_i + 1}",
        title="",
        content=content,
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
    parts = []
    idx = caption_idx + 1
    while idx < len(lines) and len(parts) < 3:
        pline = lines[idx]
        if pline.bbox[1] >= grid_top_y or not is_caption_font(pline.font):
            break
        parts.append(pline.text)
        idx += 1
    return " ".join(parts).strip(), idx


def build_table_region(
    anchor: TableAnchor,
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    page_number: int,
) -> TableRegion | None:
    caption_bottom = lines[anchor.caption_line_idx].bbox[3]
    row_ys, col_xs = _grid_boundaries(drawing_rects, below_y=caption_bottom)
    if len(row_ys) - 1 < MIN_TABLE_ROWS or len(col_xs) - 1 < MIN_TABLE_COLS:
        return None

    title, title_end_idx = _consume_table_title(lines, anchor.caption_line_idx, row_ys[0])
    forming_idx, forming_part_of = _forming_part_of_above(lines, anchor.caption_line_idx, row_ys[0])
    cell_lines, consumed = _assign_lines_to_cells(lines, row_ys, col_xs)
    consumed.add(anchor.caption_line_idx)
    consumed.update(range(anchor.caption_line_idx + 1, title_end_idx))
    if forming_idx is not None:
        consumed.add(forming_idx)

    table_citation = f"Table:{anchor.identifier}"
    rows = _build_rows(row_ys, col_xs, cell_lines, table_citation, page_number)

    outer_bbox = BBox(col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    table_node = Node(
        type="Table",
        identifier=anchor.identifier,
        citation=table_citation,
        title=title,
        page=page_number,
        end_page=page_number,
        bbox=outer_bbox,
        children=rows,
    )
    return TableRegion(
        anchor=anchor,
        table_node=table_node,
        forming_part_of=forming_part_of,
        consumed_line_indices=consumed,
        has_bottom_border=_has_bottom_border(drawing_rects, row_ys[-1]),
        outer_bbox=outer_bbox,
    )


def detect_tables_on_page(
    lines: list[PageLine], drawing_rects: list[tuple[float, float, float, float]], page_number: int
) -> list[TableRegion]:
    anchors = find_table_anchors(lines, page_number - 1)
    regions = []
    for anchor in anchors:
        region = build_table_region(anchor, lines, drawing_rects, page_number)
        if region is not None:
            regions.append(region)
    return regions


def _renumber_row(table_citation: str, row: Node, row_i: int) -> None:
    row.identifier = f"Row{row_i + 1}"
    row.citation = f"{table_citation}-{row.identifier}"
    for cell in row.children:
        cell.citation = f"{row.citation}-{cell.identifier}"


def _continues_previous(prev: TableRegion, next_region: TableRegion) -> bool:
    prev_cols = len(prev.table_node.children[0].children) if prev.table_node.children else 0
    next_cols = (
        len(next_region.table_node.children[0].children) if next_region.table_node.children else 0
    )
    same_x_range = (
        abs(prev.outer_bbox.x0 - next_region.outer_bbox.x0) <= BOUNDARY_MERGE_TOLERANCE
        and abs(prev.outer_bbox.x1 - next_region.outer_bbox.x1) <= BOUNDARY_MERGE_TOLERANCE
    )
    return not prev.has_bottom_border and prev_cols == next_cols and same_x_range


def _merge_into(pending: TableRegion, region: TableRegion) -> None:
    table_citation = pending.table_node.citation
    start = len(pending.table_node.children)
    for i, row in enumerate(region.table_node.children):
        _renumber_row(table_citation, row, start + i)
    pending.table_node.children.extend(region.table_node.children)
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


def _own_forming_part_of_reference(lines: list[PageLine]) -> str | None:
    """Deliberately UNBOUNDED (whole page, not bounded above the candidate's
    own grid top) - confirmed by direct, whole-document experiment to be
    the correct choice for this specific signal, even though it looks like
    an asymmetry against _forming_part_of_above's bounded scan on an
    anchored page.

    A bounded version was tried and reverted: real page 926 has a
    combined, single detected grid (via _grid_boundaries, which has no
    concept of "this is actually two tables' worth of rects, separated by
    an intervening 'Notes to Table ...:' heading") that spans BOTH a
    genuine continuation of a preceding table AND, further down the SAME
    page, past that Notes heading, a second, unrelated table's own
    "Forming Part of Sentence 9.24.2.5.(1)" line - which sits BELOW this
    combined grid's own top edge. Bounding the scan to "above the grid top"
    excludes that line entirely, silently re-absorbing page 926 as fake
    continuation rows (confirmed: a controlled instrument run over all
    1685 pages showed the bounded scan's accepted-page set differs from
    the unbounded scan's by EXACTLY one page - 926 - with zero other
    differences anywhere in the document). The reviewer's own concern
    (a later table's forming-part-of line polluting an earlier, genuine
    continuation's check) is a real theoretical risk, but the same
    whole-document run found zero confirmed instances of it actually
    happening - so leaving the scan unbounded is a net improvement here,
    not a compromise.
    """
    for pline in lines:
        match = RE_FORMING_PART_OF.match(pline.text)
        if match:
            return match.group(2).strip()
    return None


def _forming_part_of_conflicts(lines: list[PageLine], pending: TableRegion) -> bool:
    """A genuinely new, unrelated table can coincidentally share `pending`'s
    column count and x-range (this document uses consistent margins across
    all its tables) even on a page where detect_tables_on_page found no
    "Table X" caption trigger for it - confirmed on 4 real pages (170, 185,
    835, 926), each absorbed as fake continuation rows of a preceding,
    unrelated table before this guard existed. Such a page's own "Forming
    part of ..." line, when present, points somewhere else - a cheap, strong
    signal this is not really a continuation of `pending`, even when the
    shape happens to match.

    Compares reference-to-reference whenever possible: `pending.forming_
    part_of` is now propagated through the whole continuation chain (see
    build_continuation_region), never reset to None, so the identifier
    fallback below is reached only when the ORIGINAL anchored table
    genuinely never had a forming-part-of line at all - not, as an earlier
    round of this fix relied on by accident, whenever `pending` happened to
    be a synthesized region. Comparing a table's own identifier against a
    forming-part-of reference is a different namespace in general (e.g.
    identifier "9.24.2.1." vs. reference "9.24.2.1.(1)"); it is used here
    only as a last-resort, best-effort signal when no real reference is
    available to compare against.
    """
    candidate_ref = _own_forming_part_of_reference(lines)
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
    outer_bbox: BBox, col_count: int, expected_cols: int, pending: TableRegion
) -> bool:
    return col_count == expected_cols and (
        abs(outer_bbox.x0 - pending.outer_bbox.x0) <= BOUNDARY_MERGE_TOLERANCE
        and abs(outer_bbox.x1 - pending.outer_bbox.x1) <= BOUNDARY_MERGE_TOLERANCE
    )


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
    expected_cols = len(pending.table_node.children[-1].children)
    outer_bbox = BBox(col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    same_shape = _continuation_shape_matches(outer_bbox, len(col_xs) - 1, expected_cols, pending)
    rejected = (
        not same_shape
        or _forming_part_of_conflicts(lines, pending)
        or _has_leading_title_block(lines, row_ys[0])
    )
    if rejected:
        return None

    cell_lines, consumed = _assign_lines_to_cells(lines, row_ys, col_xs)
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

    Deliberately does NOT also handle a continuation fragment that shares a
    page with the NEXT table's own anchor (confirmed on the real document:
    Table 1.1.1.1.(5)'s final rows sit above Table 1.1.1.1.(6)'s own
    caption, both on page 12) - an earlier attempt at that bounded the rect
    scan to "everything above the next anchor's own grid top," but the real
    document has ordinary sentence body text (Sentence 1.1.1.1.(6)'s own
    prose) sitting in that same gap, with no geometric signal separating it
    from a genuine continuation row. That attempt silently misfiled that
    prose as fake table rows - a worse failure than the leak it was meant
    to close - so it was reverted rather than shipped. See task-14-report.md
    for the full investigation; this is a confirmed, documented residual
    limitation, not an oversight.
    """
    filled = [list(regions) for regions in regions_by_page]
    pending: TableRegion | None = None
    for page_index, regions in enumerate(filled):
        if regions:
            pending = _next_pending(regions)
            continue
        if pending is None:
            continue
        synthesized = _fill_one_gap(
            all_lines[page_index], all_drawing_rects[page_index], page_index + 1, pending
        )
        filled[page_index] = [synthesized] if synthesized else []
        pending = _next_pending(filled[page_index])
    return filled


def attach_tables(volume: Node, regions: list[TableRegion], captions: list[Caption] = ()) -> None:
    index = _citation_index(volume)
    for region in regions:
        division = _division_for_page(volume, region.table_node.page)
        owner_citation = resolve_owner_citation(region, division, index, volume)
        owner = index[owner_citation]
        owner.children.append(region.table_node)
        index[region.table_node.citation] = region.table_node
        caption = _matching_caption(region, captions)
        if caption is not None:
            region.table_node.title = caption.title
