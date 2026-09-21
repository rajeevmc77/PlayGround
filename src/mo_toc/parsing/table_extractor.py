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

from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.heading_rules import classify_caption_line
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

    forming_idx, forming_part_of = _forming_part_of_above(lines, anchor.caption_line_idx, row_ys[0])
    cell_lines, consumed = _assign_lines_to_cells(lines, row_ys, col_xs)
    consumed.add(anchor.caption_line_idx)
    if forming_idx is not None:
        consumed.add(forming_idx)

    table_citation = f"Table:{anchor.identifier}"
    rows = _build_rows(row_ys, col_xs, cell_lines, table_citation, page_number)

    outer_bbox = BBox(col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    table_node = Node(
        type="Table",
        identifier=anchor.identifier,
        citation=table_citation,
        title="",
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


def attach_tables(volume: Node, regions: list[TableRegion]) -> None:
    index = _citation_index(volume)
    for region in regions:
        division = _division_for_page(volume, region.table_node.page)
        owner_citation = resolve_owner_citation(region, division, index, volume)
        owner = index[owner_citation]
        owner.children.append(region.table_node)
        index[region.table_node.citation] = region.table_node
