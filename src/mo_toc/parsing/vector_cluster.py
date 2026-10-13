"""Groups vector-drawing bounding boxes (from PdfSource.page_drawing_rects) into
per-figure clusters. A technical diagram is drawn as many separate thin-stroke
path segments (axis lines, arrows, hatching) that are individually no thicker
than a table rule line or underline, so a single rect's own shape can't tell
a diagram stroke apart from a rule line. Merging nearby segments together and
judging the resulting cluster's total bounding area can: a rule line's or
underline's merged extent stays a thin sliver (low area), while a real diagram
spans a wide two-dimensional region once its strokes are merged.
"""

from itertools import combinations

from mo_toc.domain.image_classification import is_equation_shaped

BBox = tuple[float, float, float, float]

MERGE_MARGIN = 5.0  # pt; rects at most this far apart belong to the same figure
MIN_CLUSTER_AREA = 400.0  # pt^2 (~20x20pt); smaller merged clusters are rule lines/marks
# pt; a stacked formula's lines (fraction bar, summation limits, sub/
# superscripts) can sit farther apart than any diagram's own strokes ever
# do - reuses image_classification's own ceiling for how tall one equation
# can be, so this pass can never bridge a gap wider than an equation itself.
STACK_GAP_LIMIT = 70.0
# Fraction of the narrower cluster's width that must overlap horizontally
# for two clusters to plausibly be the same formula's stacked lines.
MIN_STACK_OVERLAP_FRACTION = 0.5


def _expand(rect: BBox, margin: float) -> BBox:
    x0, y0, x1, y1 = rect
    return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)


def _overlaps(a: BBox, b: BBox) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _area(rect: BBox) -> float:
    x0, y0, x1, y1 = rect
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _x_overlap(a: BBox, b: BBox) -> float:
    ax0, _, ax1, _ = a
    bx0, _, bx1, _ = b
    return max(0.0, min(ax1, bx1) - max(ax0, bx0))


def _vertical_gap(a: BBox, b: BBox) -> float:
    _, ay0, _, ay1 = a
    _, by0, _, by1 = b
    return max(ay0, by0) - min(ay1, by1)


def _is_stacked_pair(a: BBox, b: BBox) -> bool:
    gap = _vertical_gap(a, b)
    if not (0 <= gap <= STACK_GAP_LIMIT):
        return False
    narrower_width = min(a[2] - a[0], b[2] - b[0])
    return _x_overlap(a, b) >= MIN_STACK_OVERLAP_FRACTION * narrower_width


def _reads_as_equation(rect: BBox) -> bool:
    x0, y0, x1, y1 = rect
    return is_equation_shaped(x1 - x0, y1 - y0)


def _find_stackable_pair(rects: list[BBox]) -> tuple[int, int] | None:
    for i, j in combinations(range(len(rects)), 2):
        if _is_stacked_pair(rects[i], rects[j]) and _reads_as_equation(_union(rects[i], rects[j])):
            return i, j
    return None


def merge_equation_fragments(clusters: list[BBox]) -> list[BBox]:
    """Merges pairs of clusters stacked closely enough and overlapping
    enough horizontally to plausibly be one formula's separate lines - but
    only when the MERGED result itself reads as a complete equation
    (is_equation_shaped), so two genuinely separate diagrams - which never
    combine into something wide-and-short - are left untouched even if one
    sits just above the other."""
    clusters = list(clusters)
    pair = _find_stackable_pair(clusters)
    while pair is not None:
        i, j = pair
        clusters[i] = _union(clusters[i], clusters[j])
        del clusters[j]
        pair = _find_stackable_pair(clusters)
    return clusters


def _find_mergeable_pair(rects: list[BBox]) -> tuple[int, int] | None:
    for i, j in combinations(range(len(rects)), 2):
        if _overlaps(_expand(rects[i], MERGE_MARGIN), rects[j]):
            return i, j
    return None


def _merge_all_overlapping(rects: list[BBox]) -> list[BBox]:
    rects = list(rects)
    pair = _find_mergeable_pair(rects)
    while pair is not None:
        i, j = pair
        rects[i] = _union(rects[i], rects[j])
        del rects[j]
        pair = _find_mergeable_pair(rects)
    return rects


def cluster_drawing_rects(rects: list[BBox]) -> list[BBox]:
    """Merges nearby drawing rects and drops merged clusters too small in area
    to be a real figure, returning one bounding box per detected vector diagram.
    """
    merged = _merge_all_overlapping(rects)
    return [c for c in merged if _area(c) >= MIN_CLUSTER_AREA]


def exclude_overlapping_rects(clusters: list[BBox], existing: list[BBox]) -> list[BBox]:
    """Drops vector clusters that overlap an already-extracted raster image,
    so the same figure isn't captured twice.
    """
    return [c for c in clusters if not any(_overlaps(c, e) for e in existing)]
