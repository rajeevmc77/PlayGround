from pathlib import Path

from mo_toc.domain.image_classification import is_decorative, is_tagged_equation
from mo_toc.domain.models import BBox, ImageAsset
from mo_toc.parsing.image_extractor import RawImage


def _is_decorative(raw: RawImage, bbox: BBox) -> bool:
    """An icon-shaped image is decorative unless the PDF tags it a formula -
    an inline glyph like N-bar or f'c is as small and square as any icon."""
    if is_tagged_equation(raw.alt):
        return False
    return is_decorative(bbox.x1 - bbox.x0, bbox.y1 - bbox.y0)


def write_images(raw_images: list[RawImage], output_dir: str) -> list[ImageAsset]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    for i, raw in enumerate(raw_images):
        file_path = out_dir / f"img_{i}.{raw.ext}"
        file_path.write_bytes(raw.data)
        bbox = BBox(*raw.bbox)
        assets.append(
            ImageAsset(
                page=raw.page,
                bbox=bbox,
                width=raw.width,
                height=raw.height,
                phash=raw.phash,
                image_path=f"{out_dir.name}/{file_path.name}",
                decorative=_is_decorative(raw, bbox),
                alt=raw.alt,
                source_kind=raw.kind,
            )
        )
    return assets
