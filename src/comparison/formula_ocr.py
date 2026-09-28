"""Reads a formula image's text with Tesseract (its command line, so no Python
binding is needed). The image is enlarged 3x and given a white margin first:
the PDF's formula rasters are small, and Tesseract reads small text poorly.
Without Tesseract installed nothing is read, and equations are compared by
their pixels alone."""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

_SCALE = 3
_MARGIN = 20
_TIMEOUT_SECONDS = 60


def _prepared(image_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    image = image.resize((image.width * _SCALE, image.height * _SCALE), Image.Resampling.LANCZOS)
    return ImageOps.expand(image, border=_MARGIN, fill=255)


def read_formula(image_bytes: bytes) -> str:
    tesseract = shutil.which("tesseract")
    if tesseract is None:
        return ""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "formula.png"
        _prepared(image_bytes).save(path)
        result = subprocess.run(
            [tesseract, str(path), "-", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    return result.stdout
