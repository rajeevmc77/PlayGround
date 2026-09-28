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


def _figure(framed: bool) -> bytes:
    image = _solid((200, 160), (255, 255, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    for storey in range(3):
        fill = (245, 210, 222) if storey == 0 else None
        draw.rectangle(
            (50, 20 + storey * 40, 150, 60 + storey * 40), outline=(0, 0, 0), fill=fill, width=2
        )
    if framed:
        draw.rectangle((2, 2, 197, 157), outline=(0, 120, 60), width=3)
    return _bytes(image)


def test_a_figure_scores_the_better_of_its_plain_and_ink_comparisons():
    # The marked-up PDF boxes 9.23.13.7.'s house diagrams in a frame the
    # site's copy doesn't have: only the ink comparison sees past it.
    result = compare_images("B.9.23.13.7.Fig1", _figure(framed=True), _figure(framed=False))
    assert images_match(result)


def test_an_equation_keeps_the_plain_comparison():
    framed, plain = _figure(framed=True), _figure(framed=False)
    as_equation = compare_images("B.4.1.6.5.Eq1", framed, plain)
    as_figure = compare_images("B.4.1.6.5.Fig1", framed, plain)
    assert as_equation.similarity_percent < as_figure.similarity_percent


def test_a_pair_with_an_equation_on_either_side_compares_as_an_equation():
    from comparison.image_similarity import comparison_key

    assert comparison_key("A.Fig2", "A.Eq3") == "A.Eq3"
    assert comparison_key("A.Eq1", "A.Fig1") == "A.Eq1"
    assert comparison_key("A.Fig1", "A.Fig1") == "A.Fig1"
