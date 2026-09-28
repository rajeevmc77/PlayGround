"""ink_phash compares where a figure's ink falls, not its shade: the
marked-up PDF draws a figure's lines heavier or greyer than the site's copy
and boxes some figures in a frame the site's copy doesn't have
(9.23.13.7.'s house diagrams), which the plain phash reads as a different
image."""

import io

from PIL import Image, ImageDraw

from image_compare.analysis.similarity import compare
from image_compare.parsing.ink_hash import ink_phash


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _houses(shaded_storey=0, line=(0, 0, 0), size=(300, 240), scale=1.0, offset=(0, 0)):
    """Three stacked 'storeys' in each of two houses, one storey shaded pink."""
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    ox, oy = offset
    for house in range(2):
        x0 = ox + (20 + house * 120) * scale
        for storey in range(3):
            y0 = oy + (40 + storey * 60) * scale
            box = (x0, y0, x0 + 90 * scale, y0 + 60 * scale)
            fill = (245, 210, 222) if storey == shaded_storey else None
            draw.rectangle(box, outline=line, fill=fill, width=2)
    return image


def _framed(image: Image.Image) -> Image.Image:
    framed = Image.new("RGB", (image.width + 60, image.height + 60), (255, 255, 255))
    framed.paste(image, (30, 30))
    ImageDraw.Draw(framed).rectangle(
        (4, 4, framed.width - 5, framed.height - 5), outline=(0, 120, 60), width=3
    )
    return framed


def _score(a: Image.Image, b: Image.Image) -> float:
    return compare("s", ink_phash(_png(a)), ink_phash(_png(b))).similarity_percent


def test_a_frame_around_the_same_drawing_does_not_count():
    assert _score(_framed(_houses()), _houses()) >= 90


def test_grey_lines_and_black_lines_of_the_same_drawing_match():
    assert _score(_houses(line=(150, 150, 150)), _houses()) >= 90


def test_the_same_drawing_at_another_size_matches():
    assert _score(_houses(size=(600, 480), scale=2.0), _houses()) >= 90


def test_a_different_storey_shaded_is_a_different_drawing():
    assert _score(_houses(shaded_storey=0), _houses(shaded_storey=2)) < 80


def test_a_blank_image_has_a_hash():
    assert len(ink_phash(_png(Image.new("RGB", (20, 20), (255, 255, 255))))) == 64
