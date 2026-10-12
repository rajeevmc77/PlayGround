"""Builders shared by the llm_compare tests."""

import io

from PIL import Image, ImageDraw

from llm_compare.domain.models import ImagePair, PreparedImage, PreparedPair


def png_bytes(size=(60, 50), box=(10, 10, 49, 39)) -> bytes:
    """White canvas with a black rectangle (PIL boxes are inclusive: 40x30 of content) that has
    a margin to trim and content to keep."""
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle(box, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def prepared_image(width=40, height=30) -> PreparedImage:
    return PreparedImage(png_bytes(), width, height, 60, 50)


def image_pair(key="A.Fig1", pdf="images/a.png", web="web_images/a.png", **extra) -> ImagePair:
    return ImagePair(row_id=f"pdf:{pdf}", key=key, pdf_path=pdf, web_path=web, web_key=key, **extra)


def prepared_pair(key="A.Fig1", tokens=100, score=50.0, pdf="images/a.png") -> PreparedPair:
    pair = image_pair(key, pdf=pdf)
    return PreparedPair(pair, score, prepared_image(), prepared_image(), tokens)
