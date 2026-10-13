"""Extracts every embedded raster image and every vector-drawn figure from a
PdfSource, page by page, with no minimum-size filter on raster images (unlike
the archived extract_figures.py, which only kept images matched to a genuine
Figure caption above ~40pt) — this indexes every raster image in the document,
including logos/icons/decorative graphics, plus a rendered crop for each
distinct cluster of vector paths that isn't already covered by a raster image.

raster_images_on_page/vector_images_on_page are public (not prefixed) because
mo_toc.parsing.parallel_extraction also calls them directly, one page at a
time, from inside a worker process.
"""

import dataclasses
import io
from dataclasses import dataclass

from mo_toc.parsing.pdf_source import ExtractedImage, ImageAlt, PageImageInfo, PdfSource
from mo_toc.parsing.table_extractor import detect_tables_on_page, rects_form_a_grid
from mo_toc.parsing.vector_cluster import (
    cluster_drawing_rects,
    exclude_overlapping_rects,
    merge_equation_fragments,
)


@dataclass(frozen=True)
class RawImage:
    page: int
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    data: bytes
    ext: str
    phash: str | None
    # "raster" (an embedded image XObject) or "vector" (a rendered crop of a
    # clustered vector-drawing region). Lets a later pass (drop_images_over_
    # tables in build_mo_toc.py) exclude only vector-derived table-gridline
    # artifacts from a table-bbox overlap, never a genuine embedded raster
    # image - see that function's own docstring for the bug this guards
    # against.
    kind: str = "raster"
    # The tagged PDF's structure-tree /Alt for this placement (e.g. "EQUATION"
    # on every formula in the MO Package PDF); None when the page doesn't tag it.
    alt: str | None = None


# pt each edge of a tagged placement may sit off the image's own bbox: both
# are the same transform, worked out by MuPDF and by image_placements.
ALT_MATCH_TOLERANCE = 1.5


def _phash(data: bytes) -> str | None:
    import imagehash
    from PIL import Image

    try:
        return str(imagehash.phash(Image.open(io.BytesIO(data))))
    except Exception:
        return None


def _raw_image(page_index: int, bbox, extracted: ExtractedImage, kind: str = "raster") -> RawImage:
    return RawImage(
        page=page_index + 1,
        bbox=bbox,
        width=extracted.width,
        height=extracted.height,
        data=extracted.data,
        ext=extracted.ext,
        phash=_phash(extracted.data),
        kind=kind,
    )


def _as_drawn(extracted: ExtractedImage, info: PageImageInfo) -> ExtractedImage:
    """The image the way the page shows it: one the page draws flipped (the
    A-9.32.3.4 figures are drawn upside down) is turned to match, as a PNG."""
    from PIL import Image

    if not (info.flipped_x or info.flipped_y):
        return extracted
    image = Image.open(io.BytesIO(extracted.data))
    image = image.convert("RGB") if image.mode == "CMYK" else image
    if info.flipped_x:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if info.flipped_y:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return ExtractedImage(data=buf.getvalue(), ext="png", width=image.width, height=image.height)


def _alt_at(bbox, alts: list[ImageAlt]) -> str | None:
    for placed in alts:
        if all(abs(a - b) <= ALT_MATCH_TOLERANCE for a, b in zip(bbox, placed.bbox, strict=True)):
            return placed.alt
    return None


def raster_images_on_page(source: PdfSource, page_index: int) -> list[RawImage]:
    infos = source.page_images(page_index)
    alts = source.page_image_alts(page_index) if infos else []
    images = []
    for info in infos:
        extracted = _as_drawn(source.extract_image(info.xref), info)
        image = _raw_image(page_index, info.bbox, extracted, kind="raster")
        images.append(dataclasses.replace(image, alt=_alt_at(info.bbox, alts)))
    return images


def _contains(bbox: tuple[float, float, float, float], rect, margin: float) -> bool:
    x0, y0, x1, y1 = bbox
    rx0, ry0, rx1, ry1 = rect
    return x0 - margin <= rx0 and rx1 <= x1 + margin and y0 - margin <= ry0 and ry1 <= y1 + margin


def _rects_within(bbox: tuple[float, float, float, float], rects) -> list:
    return [r for r in rects if _contains(bbox, r, margin=0.5)]


def vector_images_on_page(
    source: PdfSource,
    page_index: int,
    raster_bboxes: list[tuple[float, float, float, float]],
    drawing_rects: list[tuple[float, float, float, float]] | None = None,
    table_bboxes: list[tuple[float, float, float, float]] = (),
) -> list[RawImage]:
    rects = drawing_rects if drawing_rects is not None else source.page_drawing_rects(page_index)
    clusters = cluster_drawing_rects(rects)
    clusters = merge_equation_fragments(clusters)
    clusters = exclude_overlapping_rects(clusters, list(raster_bboxes) + list(table_bboxes))
    clusters = [c for c in clusters if not rects_form_a_grid(_rects_within(c, rects))]
    images = []
    for bbox in clusters:
        extracted = source.render_region(page_index, bbox)
        images.append(_raw_image(page_index, bbox, extracted, kind="vector"))
    return images


def _table_bboxes_on_page(
    source: PdfSource, page_index: int, rects: list[tuple[float, float, float, float]]
) -> list[tuple[float, float, float, float]]:
    lines = source.page_lines(page_index)
    table_regions = detect_tables_on_page(lines, rects, page_number=page_index + 1)
    return [r.outer_bbox.as_tuple() for r in table_regions]


def extract_images(source: PdfSource) -> list[RawImage]:
    images = []
    for page_index in range(source.page_count):
        raster = raster_images_on_page(source, page_index)
        images.extend(raster)
        rects = source.page_drawing_rects(page_index)
        table_bboxes = _table_bboxes_on_page(source, page_index, rects)
        vector = vector_images_on_page(
            source, page_index, [r.bbox for r in raster], rects, table_bboxes
        )
        images.extend(vector)
    return images
