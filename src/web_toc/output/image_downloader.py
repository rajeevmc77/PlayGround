import sys
from pathlib import Path

from web_toc.domain.models import WebImage
from web_toc.parsing.site_source import WebSource


def download_images(images: list[WebImage], source: WebSource, output_dir: str) -> None:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for img in images:
        if not img.src:
            continue
        content = source.fetch_image(img.src)
        if content is None:
            print(f"  skipped image {img.id} (fetch failed)", file=sys.stderr)
            continue
        file_name = f"{img.id}.jpg"
        (out_dir / file_name).write_bytes(content)
        img.local_path = f"{out_dir.name}/{file_name}"
