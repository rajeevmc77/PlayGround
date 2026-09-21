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

_worker_source: PyMuPdfSource | None = None


def _init_worker(pdf_path: str) -> None:
    global _worker_source
    _worker_source = PyMuPdfSource(pdf_path)


def _extract_page(page_index: int) -> tuple[list[PageLine], list[RawImage]]:
    assert _worker_source is not None
    lines = _worker_source.page_lines(page_index)
    raster = raster_images_on_page(_worker_source, page_index)
    vector = vector_images_on_page(_worker_source, page_index, [r.bbox for r in raster])
    return lines, raster + vector


def extract_all_pages(
    pdf_path: str, max_workers: int | None = None
) -> tuple[list[list[PageLine]], list[RawImage]]:
    page_count = PyMuPdfSource(pdf_path).page_count
    workers = max_workers or os.cpu_count() or 1
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(pdf_path,)
    ) as executor:
        results = list(executor.map(_extract_page, range(page_count)))
    all_lines = [lines for lines, _ in results]
    all_images = [image for _, images in results for image in images]
    return all_lines, all_images
