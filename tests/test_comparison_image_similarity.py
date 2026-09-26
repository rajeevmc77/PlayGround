import io
from pathlib import Path

from PIL import Image

from comparison.image_similarity import compare_images, images_match
from image_compare.domain.models import ComparisonResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def _solid(size, color) -> Image.Image:
    return Image.new("RGB", size, color)


def test_identical_images_compare_as_a_perfect_match():
    image_bytes = _bytes(_solid((80, 80), (10, 20, 30)))
    result = compare_images("A.Fig1", image_bytes, image_bytes)
    assert result.stem == "A.Fig1"
    assert result.similarity_percent == 100.0


def test_compares_a_real_pdf_render_against_its_downloaded_web_jpeg():
    # Same pair test_image_compare_autocrop.py already establishes scores
    # >75% after autocrop - this confirms compare_images wires autocrop +
    # phash + the Hamming-distance formula together the same way, end to end.
    pdf_bytes = (
        PROJECT_ROOT / "compare-images" / "pdf" / "nbc.divA.part1.appendix.appnote2b.figure1.png"
    ).read_bytes()
    web_bytes = (
        PROJECT_ROOT / "compare-images" / "web" / "nbc.divA.part1.appendix.appnote2b.figure1.jpg"
    ).read_bytes()
    result = compare_images("appnote2b", pdf_bytes, web_bytes)
    assert result.stem == "appnote2b"
    assert result.similarity_percent > 75.0


def test_images_match_is_true_at_or_above_80_percent():
    result = ComparisonResult(stem="s", hash_distance=12, similarity_percent=81.25)
    assert images_match(result) is True


def test_images_match_is_false_below_80_percent():
    result = ComparisonResult(stem="s", hash_distance=13, similarity_percent=79.7)
    assert images_match(result) is False


def test_images_match_honors_a_custom_threshold():
    result = ComparisonResult(stem="s", hash_distance=20, similarity_percent=68.8)
    assert images_match(result, threshold_percent=60.0) is True
    assert images_match(result, threshold_percent=80.0) is False
