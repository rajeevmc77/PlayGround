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

import io
from dataclasses import dataclass

from mo_toc.parsing.pdf_source import ExtractedImage, PdfSource
from mo_toc.parsing.table_extractor import detect_tables_on_page
from mo_toc.parsing.vector_cluster import cluster_drawing_rects, exclude_overlapping_rects


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


def raster_images_on_page(source: PdfSource, page_index: int) -> list[RawImage]:
    images = []
    for info in source.page_images(page_index):
        extracted = source.extract_image(info.xref)
        images.append(_raw_image(page_index, info.bbox, extracted, kind="raster"))
    return images


def vector_images_on_page(
    source: PdfSource,
    page_index: int,
    raster_bboxes: list[tuple[float, float, float, float]],
    drawing_rects: list[tuple[float, float, float, float]] | None = None,
    table_bboxes: list[tuple[float, float, float, float]] = (),
) -> list[RawImage]:
    rects = drawing_rects if drawing_rects is not None else source.page_drawing_rects(page_index)
    clusters = cluster_drawing_rects(rects)
    clusters = exclude_overlapping_rects(clusters, list(raster_bboxes) + list(table_bboxes))
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
