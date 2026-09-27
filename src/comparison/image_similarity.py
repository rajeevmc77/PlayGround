"""Perceptual-hash comparison between a PDF-embedded image and its web
counterpart, reusing image_compare's autocrop+phash pipeline (built for
exactly this PDF-render-vs-downloaded-JPEG pairing) rather than
re-implementing it."""

import re

from image_compare.analysis.similarity import compare as _compare_hashes
from image_compare.domain.models import ComparisonResult
from image_compare.parsing.autocrop import autocrop_to_content
from image_compare.parsing.phash import compute_phash

DEFAULT_THRESHOLD_PERCENT = 80.0
# A PDF formula raster (small, in its own typeface) against the site's
# MathJax render tops out lower than a figure pair: on the real data, correct
# equation pairs score a median 75% while no wrong pairing reached 70%.
EQUATION_THRESHOLD_PERCENT = 70.0
_EQUATION_KEY = re.compile(r"\.Eq\d+$")


def threshold_for(unified_number: str, default_percent: float) -> float:
    if _EQUATION_KEY.search(unified_number):
        return EQUATION_THRESHOLD_PERCENT
    return default_percent


def _comparable_phash(image_bytes: bytes) -> str:
    return compute_phash(autocrop_to_content(image_bytes))


def compare_images(stem: str, pdf_image_bytes: bytes, web_image_bytes: bytes) -> ComparisonResult:
    return _compare_hashes(
        stem, _comparable_phash(pdf_image_bytes), _comparable_phash(web_image_bytes)
    )


def images_match(
    result: ComparisonResult, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT
) -> bool:
    return result.similarity_percent >= threshold_percent
