"""Perceptual-hash comparison between a PDF-embedded image and its web
counterpart, reusing image_compare's autocrop+phash pipeline (built for
exactly this PDF-render-vs-downloaded-JPEG pairing) rather than
re-implementing it."""

from image_compare.analysis.similarity import compare as _compare_hashes
from image_compare.domain.models import ComparisonResult
from image_compare.parsing.autocrop import autocrop_to_content
from image_compare.parsing.phash import compute_phash

DEFAULT_THRESHOLD_PERCENT = 80.0


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
