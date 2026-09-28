import io
import shutil

import pytest
from PIL import Image, ImageDraw

from comparison import formula_ocr
from comparison.formula_ocr import read_formula


def _text_png(text: str) -> bytes:
    image = Image.new("RGB", (220, 30), (255, 255, 255))
    ImageDraw.Draw(image).text((5, 8), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_without_tesseract_nothing_is_read(monkeypatch):
    monkeypatch.setattr(formula_ocr.shutil, "which", lambda _name: None)
    assert read_formula(_text_png("Area = 0.24")) == ""


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_reads_a_formula_images_text():
    assert "0.24" in read_formula(_text_png("Area = 0.24"))
