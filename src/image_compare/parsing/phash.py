import io

import imagehash
from PIL import Image


def compute_phash(image_bytes: bytes) -> str:
    """Perceptual hash as a 16-character hex string, matching the format
    mo_toc.parsing.image_extractor already stores for embedded PDF images -
    robust to the PNG/JPEG format and compression differences between the
    PDF-rendered and website-downloaded versions of the same figure."""
    return str(imagehash.phash(Image.open(io.BytesIO(image_bytes))))
