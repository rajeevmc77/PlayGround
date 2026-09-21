"""Extracts every page's lines and images in parallel across worker
processes. Profiling the real 1685-page document showed the pipeline is
CPU-bound (98% CPU, one core, ~69s wall-clock) with no I/O wait to overlap -
threads/asyncio can't help here, since the GIL still serializes CPU work.
Real speedup needs process-level parallelism.

Each worker opens its own PyMuPdfSource once (via the pool initializer) and
reuses it for every page it's assigned - reopening the PDF per page would
cost ~45ms each, more than 1685 pages' worth of overhead alone.
"""

import os
from concurrent.futures import ProcessPoolExecutor

from mo_toc.parsing.image_extractor import RawImage, raster_images_on_page, vector_images_on_page
from mo_toc.parsing.pdf_source import PageLine, PyMuPdfSource
from mo_toc.parsing.table_extractor import TableRegion, detect_tables_on_page

_worker_source: PyMuPdfSource | None = None


def _init_worker(pdf_path: str) -> None:
    global _worker_source
    _worker_source = PyMuPdfSource(pdf_path)


def _extract_page(page_index: int) -> tuple[list[PageLine], list[RawImage], list[TableRegion]]:
    assert _worker_source is not None
    lines = _worker_source.page_lines(page_index)
    raster = raster_images_on_page(_worker_source, page_index)
    rects = _worker_source.page_drawing_rects(page_index)
    table_regions = detect_tables_on_page(lines, rects, page_number=page_index + 1)
    table_bboxes = [r.outer_bbox.as_tuple() for r in table_regions]
    vector = vector_images_on_page(
        _worker_source, page_index, [r.bbox for r in raster], rects, table_bboxes
    )
    return lines, raster + vector, table_regions


def _unzip_results(
    results: list[tuple[list[PageLine], list[RawImage], list[TableRegion]]],
) -> tuple[list[list[PageLine]], list[RawImage], list[list[TableRegion]]]:
    all_lines: list[list[PageLine]] = []
    all_images: list[RawImage] = []
    all_table_regions: list[list[TableRegion]] = []
    for lines, images, regions in results:
        all_lines.append(lines)
        all_images.extend(images)
        all_table_regions.append(regions)
    return all_lines, all_images, all_table_regions


def extract_all_pages(
    pdf_path: str, max_workers: int | None = None
) -> tuple[list[list[PageLine]], list[RawImage], list[list[TableRegion]]]:
    page_count = PyMuPdfSource(pdf_path).page_count
    workers = max_workers or os.cpu_count() or 1
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(pdf_path,)
    ) as executor:
        results = list(executor.map(_extract_page, range(page_count)))
    return _unzip_results(results)
