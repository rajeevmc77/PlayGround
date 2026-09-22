import io

from PIL import Image, ImageChops

NOISE_TOLERANCE = 24


def autocrop_to_content(image_bytes: bytes, noise_tolerance: int = NOISE_TOLERANCE) -> bytes:
    """Crops away the uniform border around an image's content, re-encoded
    as PNG - corrects for the differing whitespace padding and aspect
    ratios that PDF-rendered and website-downloaded copies of the same
    figure otherwise carry into a phash comparison. noise_tolerance ignores
    per-pixel drift up to that amount, since JPEG compression alone shifts
    "background" pixels away from the sampled corner color everywhere in
    the image, not just where real content is."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, background).convert("L")
    thresholded = diff.point(lambda pixel: 255 if pixel > noise_tolerance else 0)
    bbox = thresholded.getbbox()
    cropped = image.crop(bbox) if bbox else image
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()
