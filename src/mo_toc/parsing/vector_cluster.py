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

BBox = tuple[float, float, float, float]

MERGE_MARGIN = 5.0  # pt; rects at most this far apart belong to the same figure
MIN_CLUSTER_AREA = 400.0  # pt^2 (~20x20pt); smaller merged clusters are rule lines/marks


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
