import io

from PIL import Image

from image_compare.parsing.phash import compute_phash


def _png_bytes(size=(32, 32), color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _checkerboard_jpeg_bytes(size=(32, 32)):
    image = Image.new("RGB", size, (0, 0, 0))
    for x in range(size[0]):
        for y in range(size[1]):
            if (x // 4 + y // 4) % 2 == 0:
                image.putpixel((x, y), (255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def test_identical_images_produce_identical_phash():
    data = _png_bytes()
    assert compute_phash(data) == compute_phash(data)


def test_same_image_survives_a_png_to_jpeg_round_trip():
    png_bytes = _checkerboard_jpeg_bytes()
    reencoded = io.BytesIO()
    Image.open(io.BytesIO(png_bytes)).convert("RGB").save(reencoded, format="PNG")
    assert compute_phash(png_bytes) == compute_phash(reencoded.getvalue())


def test_visually_different_images_produce_different_phash():
    solid = _png_bytes(color=(255, 0, 0))
    checkerboard = _checkerboard_jpeg_bytes()
    assert compute_phash(solid) != compute_phash(checkerboard)


def test_phash_is_a_16_character_hex_string():
    phash = compute_phash(_png_bytes())
    assert len(phash) == 16
    int(phash, 16)  # raises ValueError if not valid hex
