import io
from pathlib import Path

from PIL import Image

from image_compare.analysis.similarity import compare
from image_compare.parsing.autocrop import autocrop_to_content
from image_compare.parsing.phash import compute_phash

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def _canvas_with_content(canvas_size, content_box, background=(255, 255, 255), fill=(0, 0, 0)):
    image = Image.new("RGB", canvas_size, background)
    left, top, right, bottom = content_box
    for x in range(left, right):
        for y in range(top, bottom):
            image.putpixel((x, y), fill)
    return image


def test_crops_uniform_border_down_to_the_content_bounding_box():
    image = _canvas_with_content(canvas_size=(100, 100), content_box=(30, 40, 50, 60))
    cropped = Image.open(io.BytesIO(autocrop_to_content(_bytes(image))))
    assert cropped.size == (20, 20)


def test_image_with_content_touching_every_edge_is_unchanged():
    image = Image.new("RGB", (40, 40), (0, 0, 0))
    cropped = Image.open(io.BytesIO(autocrop_to_content(_bytes(image))))
    assert cropped.size == (40, 40)


def test_same_content_with_different_padding_crops_to_the_same_size():
    tight = _canvas_with_content(canvas_size=(60, 30), content_box=(0, 0, 60, 30))
    padded = _canvas_with_content(canvas_size=(200, 150), content_box=(70, 60, 130, 90))
    tight_cropped = Image.open(io.BytesIO(autocrop_to_content(_bytes(tight))))
    padded_cropped = Image.open(io.BytesIO(autocrop_to_content(_bytes(padded))))
    assert tight_cropped.size == padded_cropped.size == (60, 30)


def test_autocropping_the_real_appnote2b_pair_substantially_improves_phash_similarity():
    pdf_path = (
        PROJECT_ROOT / "compare-images" / "pdf" / "nbc.divA.part1.appendix.appnote2b.figure1.png"
    )
    web_path = (
        PROJECT_ROOT / "compare-images" / "web" / "nbc.divA.part1.appendix.appnote2b.figure1.jpg"
    )
    pdf_hash = compute_phash(autocrop_to_content(pdf_path.read_bytes()))
    web_hash = compute_phash(autocrop_to_content(web_path.read_bytes()))
    result = compare("appnote2b", pdf_hash, web_hash)
    # Uncropped, this pair scores 59.4% (distance 26/64) because the PDF
    # render carries ~65px of whitespace padding that the tightly-bled web
    # JPEG doesn't - padding the phash pipeline otherwise treats as content.
    assert result.similarity_percent > 75.0
