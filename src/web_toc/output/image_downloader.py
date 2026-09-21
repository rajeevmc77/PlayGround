import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from web_toc.domain.models import WebImage
from web_toc.parsing.site_source import WebSource

# I/O-bound HTTP fetches, not CPU work - a small worker pool overlaps the
# per-request latency without hammering the site with unbounded concurrency.
DOWNLOAD_WORKERS = 8


def download_images(images: list[WebImage], source: WebSource, output_dir: str) -> None:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [img for img in images if img.src]
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        contents = executor.map(lambda img: source.fetch_image(img.src), targets)
        for img, content in zip(targets, contents, strict=True):
            _write_image(img, content, out_dir)


def _write_image(img: WebImage, content: bytes | None, out_dir: Path) -> None:
    if content is None:
        print(f"  skipped image {img.id} (fetch failed)", file=sys.stderr)
        return
    file_name = f"{img.id}.jpg"
    (out_dir / file_name).write_bytes(content)
    img.local_path = f"{out_dir.name}/{file_name}"
