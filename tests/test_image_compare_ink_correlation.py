"""ink_correlation compares two figures' ink pixel by pixel at a coarse
24x24 grid, after the frame is stepped inside and the ink cropped. The
marked-up PDF embeds 9.23.13.7.'s single-house diagrams as ~40x97px rasters
in a frame; at that size a perceptual hash can't tell the same drawing from
another house variant, while the ink's layout still can."""

import io

from PIL import Image, ImageDraw

from image_compare.analysis.ink_correlation import ink_correlation


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _house(shaded_storey=2, size=(130, 420), framed=False):
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    w, h = size
    left, right, top = w * 0.15, w * 0.85, h * 0.12
    storey = (h * 0.85 - top) / 3
    draw.polygon([(left, top), (w / 2, h * 0.03), (right, top)], outline=(0, 0, 0))
    for n in range(3):
        box = (left, top + n * storey, right, top + (n + 1) * storey)
        draw.rectangle(box, outline=(0, 0, 0), fill=(245, 205, 225) if n == shaded_storey else None)
    if framed:
        draw.rectangle((0, 0, w - 1, h - 1), outline=(0, 120, 60), width=2)
    return image


def test_a_small_framed_copy_correlates_with_the_same_drawing():
    small = _house(size=(42, 98), framed=True)
    assert ink_correlation(_png(small), _png(_house())) >= 0.83


def test_another_storey_shaded_does_not_correlate_as_much():
    assert ink_correlation(_png(_house(shaded_storey=0)), _png(_house(shaded_storey=2))) < 0.83


def test_a_blank_image_correlates_with_nothing():
    blank = Image.new("RGB", (40, 40), (255, 255, 255))
    assert ink_correlation(_png(blank), _png(_house())) == 0.0
