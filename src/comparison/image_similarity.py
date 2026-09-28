"""Perceptual-hash comparison between a PDF-embedded image and its web
counterpart, reusing image_compare's autocrop+phash pipeline (built for
exactly this PDF-render-vs-downloaded-JPEG pairing) rather than
re-implementing it."""

import re

from image_compare.analysis.similarity import compare as _compare_hashes
from image_compare.domain.models import ComparisonResult
from image_compare.parsing.autocrop import autocrop_to_content
from image_compare.parsing.ink_hash import ink_phash
from image_compare.parsing.phash import compute_phash

DEFAULT_THRESHOLD_PERCENT = 80.0
# A PDF formula raster (small, in its own typeface) against the site's
# MathJax render tops out lower than a figure pair: on the real data, correct
# equation pairs score a median 75% while no wrong pairing reached 70%.
EQUATION_THRESHOLD_PERCENT = 70.0
_EQUATION_KEY = re.compile(r"\.Eq\d+$")


def comparison_key(pdf_number: str, web_number: str) -> str:
    """The key a pair is compared under: an equation on either side makes it
    an equation pair (4.1.6.5.'s formula the PDF reads as a figure)."""
    return web_number if _EQUATION_KEY.search(web_number) else pdf_number


def threshold_for(unified_number: str, default_percent: float) -> float:
    if _EQUATION_KEY.search(unified_number):
        return EQUATION_THRESHOLD_PERCENT
    return default_percent


def _comparable_phash(image_bytes: bytes) -> str:
    return compute_phash(autocrop_to_content(image_bytes))


def compare_images(stem: str, pdf_image_bytes: bytes, web_image_bytes: bytes) -> ComparisonResult:
    """A figure scores the better of the plain comparison and the ink one
    (image_compare/parsing/ink_hash.py), which sees past the marked-up PDF's
    heavier lines and frames; an equation, the plain one only - a formula's
    typeface differs on each side however its ink is read."""
    plain = _compare_hashes(
        stem, _comparable_phash(pdf_image_bytes), _comparable_phash(web_image_bytes)
    )
    if _EQUATION_KEY.search(stem):
        return plain
    ink = _compare_hashes(stem, ink_phash(pdf_image_bytes), ink_phash(web_image_bytes))
    return max(plain, ink, key=lambda result: result.similarity_percent)


def images_match(
    result: ComparisonResult, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT
) -> bool:
    return result.similarity_percent >= threshold_percent
