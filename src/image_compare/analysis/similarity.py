from image_compare.domain.models import ComparisonResult

_HASH_BITS = 64  # imagehash.phash's default hash_size=8 produces an 8x8-bit hash.


def compare(stem: str, pdf_phash: str, web_phash: str) -> ComparisonResult:
    """Hamming distance between two hex-encoded perceptual hashes, converted
    to a 0-100% similarity score. Pure integer/string math so this stays
    testable without decoding real images."""
    distance = bin(int(pdf_phash, 16) ^ int(web_phash, 16)).count("1")
    similarity_percent = round((1 - distance / _HASH_BITS) * 100, 1)
    return ComparisonResult(
        stem=stem, hash_distance=distance, similarity_percent=similarity_percent
    )
