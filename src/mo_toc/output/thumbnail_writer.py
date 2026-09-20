from pathlib import Path

from mo_toc.domain.models import BBox, ImageAsset
from mo_toc.parsing.image_extractor import RawImage


def write_thumbnails(raw_images: list[RawImage], output_dir: str) -> list[ImageAsset]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    for i, raw in enumerate(raw_images):
        file_path = out_dir / f"img_{i}.{raw.ext}"
        file_path.write_bytes(raw.data)
        assets.append(
            ImageAsset(
                page=raw.page,
                bbox=BBox(*raw.bbox),
                width=raw.width,
                height=raw.height,
                phash=raw.phash,
                thumbnail_path=f"{out_dir.name}/{file_path.name}",
            )
        )
    return assets
