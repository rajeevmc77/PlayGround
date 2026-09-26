"""Classifies an image's bounding box as decorative noise - a small,
roughly-square shape, the kind a logo/icon/bullet leaves behind - versus
meaningful content worth surfacing in the Table of Images.

A single-line formula crop (e.g. "F = 0.35*beta*sqrt(...)") is routinely
shorter than a decorative icon but far wider, so testing only the smaller
dimension (the viewer's original "hide images under 40pt" rule) misclassified
wide, short equations as noise - confirmed on Article 4.1.6.5.'s Sentence
(3), whose F=... and h'p=... formulas are ~190-260pt wide but under 40pt
tall. Requiring BOTH a near-square aspect ratio AND a small area keeps
genuine icons/logos hidden while letting any wide-but-short (or tall-but-
narrow) content through regardless of size.
"""

MAX_NOISE_ASPECT_RATIO = (
    2.0  # long side / short side, at or below which a shape reads as square-ish
)
MAX_NOISE_AREA = 1600.0  # pt^2 - equivalent to a 40x40pt icon


def is_decorative(width: float, height: float) -> bool:
    if width <= 0 or height <= 0:
        return False
    long_side, short_side = max(width, height), min(width, height)
    is_square_ish = long_side / short_side <= MAX_NOISE_ASPECT_RATIO
    is_small = (width * height) < MAX_NOISE_AREA
    return is_square_ish and is_small


def is_equation_shaped(width: float, height: float) -> bool:
    """A rendered inline formula reads left-to-right on one text line, so its
    crop is always wider than tall - unlike a diagram, which is as likely to
    be portrait or square. Reuses the same aspect-ratio boundary as
    is_decorative's "square-ish" test, just on the opposite side of it."""
    if width <= 0 or height <= 0 or width <= height:
        return False
    return width / height >= MAX_NOISE_ASPECT_RATIO
