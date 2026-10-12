"""The perceptual-hash score the routing is based on: the same score the comparison engine
uses (better of plain and ink phash for figures, plain for equations)."""

from comparison.image_similarity import compare_images, comparison_key
from llm_compare.domain.models import ImagePair


def score_pair(pair: ImagePair, pdf_bytes: bytes, web_bytes: bytes) -> float:
    key = comparison_key(pair.key, pair.web_key or pair.key)
    return compare_images(key, pdf_bytes, web_bytes).similarity_percent
