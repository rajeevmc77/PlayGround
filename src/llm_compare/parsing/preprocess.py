"""Makes one image cheap to send without hiding any of its content: transparency flattened
onto white, blank margins trimmed, scaled down (never up) to fit max_edge, lossless PNG.
Gemini bills image tokens by pixel dimensions, not file bytes, so lossy encoding would add
risk and save nothing."""

import io

from PIL import Image

from image_compare.parsing.autocrop import autocrop_to_content
from llm_compare.domain.models import PreparedImage


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _flatten_to_png(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    canvas.alpha_composite(rgba)
    return _encode(canvas.convert("RGB"))


def _fit_within(image: Image.Image, max_edge: int) -> Image.Image:
    longest = max(image.size)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def prepare_image(data: bytes, max_edge: int) -> PreparedImage:
    source = Image.open(io.BytesIO(data))
    source_width, source_height = source.size
    trimmed = Image.open(io.BytesIO(autocrop_to_content(_flatten_to_png(source))))
    fitted = _fit_within(trimmed, max_edge)
    return PreparedImage(
        png=_encode(fitted),
        width=fitted.width,
        height=fitted.height,
        source_width=source_width,
        source_height=source_height,
    )
