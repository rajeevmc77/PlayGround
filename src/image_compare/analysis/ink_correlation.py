"""How closely two figures' ink lines up, pixel by pixel, at a coarse grid.

The marked-up PDF embeds 9.23.13.7.'s single-house diagrams as ~40x97px
rasters in a frame, against the site's 130x419px copies. At that size a
perceptual hash scores the same drawing no higher than another house
variant, but the ink's own layout - which storey is shaded, where the roof
is - still lines up: both figures' ink (parsing/ink_hash.py, frame stepped
inside and cropped) is shrunk to 24x24 and correlated, 1.0 for the same
layout, near 0 for unrelated ones."""

import numpy as np
from PIL import Image

from image_compare.parsing.ink_hash import ink_content

GRID = (24, 24)


def _ink_vector(image_bytes: bytes) -> np.ndarray:
    ink = ink_content(image_bytes).convert("L").resize(GRID, Image.Resampling.BOX)
    values = 255.0 - np.asarray(ink, dtype=float)
    return values - values.mean()


def ink_correlation(pdf_image_bytes: bytes, web_image_bytes: bytes) -> float:
    a, b = _ink_vector(pdf_image_bytes), _ink_vector(web_image_bytes)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float((a * b).sum() / norm) if norm else 0.0
