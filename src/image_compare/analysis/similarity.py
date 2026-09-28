from image_compare.domain.models import ComparisonResult


def compare(stem: str, pdf_phash: str, web_phash: str) -> ComparisonResult:
    """Hamming distance between two hex-encoded perceptual hashes, converted
    to a 0-100% similarity score. Pure integer/string math so this stays
    testable without decoding real images."""
    distance = bin(int(pdf_phash, 16) ^ int(web_phash, 16)).count("1")
    bits = len(pdf_phash) * 4  # 64 for the plain 8x8 phash, 256 for ink_phash's 16x16
    similarity_percent = round((1 - distance / bits) * 100, 1)
    return ComparisonResult(
        stem=stem, hash_distance=distance, similarity_percent=similarity_percent
    )
