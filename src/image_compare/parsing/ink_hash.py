"""A perceptual hash of where a figure's ink falls, not how dark it is.

The marked-up PDF draws many figures' lines and hatching heavier or greyer
than the site's copy, and boxes some in a frame the site's copy doesn't have
(9.23.13.7.'s house diagrams sit in a green MRK box). The plain phash
(phash.py) reads each of those as a different image. Here every pixel darker
than near-white is ink and the rest paper, a frame drawn around the content
is stepped inside, and the ink is cropped to its own extent before hashing -
at 16x16, finer than the plain 8x8 hash, so what stays apart is where the
drawing differs (which storey is shaded), not its line weight."""

import io

import imagehash
from PIL import Image, ImageOps

INK_LEVEL = 245  # grey level below which a pixel is ink, not paper
HASH_SIZE = 16
_FRAME_COVER = 0.9  # an edge line this much ink runs the whole side: a frame
_LINE_COVER = 0.5  # an edge row/column this much ink is still the frame's line
_MIN_SIDE = 20


def _ink_mask(image: Image.Image) -> Image.Image:
    """Ink black (0), paper white (255)."""
    return ImageOps.grayscale(image.convert("RGB")).point(lambda v: 0 if v < INK_LEVEL else 255)


def _cropped_to_ink(mask: Image.Image) -> Image.Image:
    box = ImageOps.invert(mask).getbbox()
    return mask.crop(box) if box else mask


def _ink_share(mask: Image.Image, box: tuple[int, int, int, int]) -> float:
    strip = mask.crop(box)
    return strip.histogram()[0] / (strip.width * strip.height)


def _row(mask: Image.Image, y: int) -> tuple[int, int, int, int]:
    return (0, y, mask.width, y + 1)


def _column(mask: Image.Image, x: int) -> tuple[int, int, int, int]:
    return (x, 0, x + 1, mask.height)


def _is_framed(mask: Image.Image) -> bool:
    width, height = mask.size
    edges = (_row(mask, 0), _row(mask, height - 1), _column(mask, 0), _column(mask, width - 1))
    return min(_ink_share(mask, edge) for edge in edges) >= _FRAME_COVER


def _frame_depth(mask: Image.Image, strip, limit: int) -> int:
    """How many rows/columns in from an edge the frame's line runs."""
    depth = 0
    while depth < limit and _ink_share(mask, strip(depth)) > _LINE_COVER:
        depth += 1
    return depth


def _inside_frame(mask: Image.Image) -> Image.Image:
    width, height = mask.size
    top = _frame_depth(mask, lambda d: _row(mask, d), height // 4)
    bottom = _frame_depth(mask, lambda d: _row(mask, height - 1 - d), height // 4)
    left = _frame_depth(mask, lambda d: _column(mask, d), width // 4)
    right = _frame_depth(mask, lambda d: _column(mask, width - 1 - d), width // 4)
    return mask.crop((left, top, width - right, height - bottom))


def _content(mask: Image.Image) -> Image.Image:
    """The ink cropped to its extent, inside any frame around it."""
    mask = _cropped_to_ink(mask)
    for _ in range(2):
        if min(mask.size) < _MIN_SIDE or not _is_framed(mask):
            break
        mask = _cropped_to_ink(_inside_frame(mask))
    return mask


def ink_content(image_bytes: bytes) -> Image.Image:
    """The figure's ink (black on white), inside any frame, cropped to it."""
    return _content(_ink_mask(Image.open(io.BytesIO(image_bytes))))


def ink_phash(image_bytes: bytes) -> str:
    """16x16 perceptual hash (64 hex characters) of the figure's ink."""
    return str(imagehash.phash(ink_content(image_bytes), hash_size=HASH_SIZE))
