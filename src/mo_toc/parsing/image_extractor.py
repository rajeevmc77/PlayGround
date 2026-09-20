"""Extracts every embedded raster image from a PdfSource, page by page, with
no minimum-size filter (unlike the archived extract_figures.py, which only
kept images matched to a genuine Figure caption above ~40pt) — this indexes
every image in the document, including logos/icons/decorative graphics.
"""

import io
from dataclasses import dataclass

from mo_toc.parsing.pdf_source import PdfSource


@dataclass(frozen=True)
class RawImage:
    page: int
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    data: bytes
    ext: str
    phash: str | None


def _phash(data: bytes) -> str | None:
    import imagehash
    from PIL import Image

    try:
        return str(imagehash.phash(Image.open(io.BytesIO(data))))
    except Exception:
        return None


def extract_images(source: PdfSource) -> list[RawImage]:
    images = []
    for page_index in range(source.page_count):
        for info in source.page_images(page_index):
            extracted = source.extract_image(info.xref)
            images.append(
                RawImage(
                    page=page_index + 1,
                    bbox=info.bbox,
                    width=extracted.width,
                    height=extracted.height,
                    data=extracted.data,
                    ext=extracted.ext,
                    phash=_phash(extracted.data),
                )
            )
    return images
