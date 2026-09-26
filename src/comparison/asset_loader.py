"""Resolves a PDF ImageAsset or WebImage entry's raster bytes on disk. Both
bcbc_pdf.json's `image_path` and bcbc_web.json's `local_path` are already
relative to the same shared output/ directory."""

from pathlib import Path


def load_pdf_image_bytes(output_dir: Path | str, pdf_image: dict) -> bytes | None:
    path = Path(output_dir) / pdf_image["image_path"]
    return path.read_bytes() if path.is_file() else None


def load_web_image_bytes(output_dir: Path | str, web_image: dict) -> bytes | None:
    local_path = web_image.get("local_path") or ""
    if not local_path:
        return None
    path = Path(output_dir) / local_path
    return path.read_bytes() if path.is_file() else None
