import io

import pytest
from PIL import Image, ImageDraw

from llm_compare.parsing.preprocess import prepare_image
from tests.llm_compare_support import png_bytes


def _decode(prepared):
    return Image.open(io.BytesIO(prepared.png))


def test_blank_margins_are_trimmed_and_source_size_is_recorded():
    prepared = prepare_image(png_bytes(), max_edge=1024)
    assert (prepared.width, prepared.height) == (40, 30)
    assert (prepared.source_width, prepared.source_height) == (60, 50)


def test_a_large_image_is_scaled_down_keeping_its_aspect_ratio():
    big = Image.new("RGB", (2000, 1000), "white")
    ImageDraw.Draw(big).rectangle((100, 100, 1899, 899), fill="black")
    buffer = io.BytesIO()
    big.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert (prepared.width, prepared.height) == (1024, 455)
    assert _decode(prepared).size == (1024, 455)


def test_a_small_image_is_never_enlarged():
    prepared = prepare_image(png_bytes(), max_edge=4096)
    assert (prepared.width, prepared.height) == (40, 30)


def test_a_very_thin_image_keeps_at_least_one_pixel():
    thin = Image.new("RGB", (3000, 4), "black")
    buffer = io.BytesIO()
    thin.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=300)
    assert prepared.width == 300 and prepared.height >= 1


def test_transparency_is_flattened_onto_white_before_trimming():
    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).rectangle((30, 30, 69, 69), fill=(0, 0, 0, 255))
    buffer = io.BytesIO()
    rgba.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert (prepared.width, prepared.height) == (40, 40)


@pytest.mark.parametrize("mode", ["P", "L", "1", "RGBA"])
def test_palette_greyscale_bilevel_and_alpha_modes_do_not_crash(mode):
    image = Image.new("RGB", (80, 60), "white")
    ImageDraw.Draw(image).rectangle((20, 10, 60, 50), fill="black")
    buffer = io.BytesIO()
    image.convert(mode).save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert 0 < prepared.width <= 80 and 0 < prepared.height <= 60


def test_a_uniform_image_is_kept_whole():
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert (prepared.width, prepared.height) == (30, 20)


def test_the_output_is_deterministic():
    assert prepare_image(png_bytes(), 512).png == prepare_image(png_bytes(), 512).png


def test_bytes_that_are_not_an_image_raise_oserror():
    with pytest.raises(OSError):
        prepare_image(b"not an image", max_edge=1024)
