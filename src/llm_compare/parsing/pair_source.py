"""Turns the PDF and web image indexes plus comparison.json's `counterparts` into one
ImagePair per report row: every PDF image, then every web image no PDF image pairs with."""

from llm_compare.domain.models import ImagePair, PdfLocation, WebLocation


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _box(raw) -> tuple | None:
    if not isinstance(raw, dict):
        return None
    corners = tuple(raw.get(corner) for corner in ("x0", "y0", "x1", "y1"))
    return corners if all(_is_number(corner) for corner in corners) else None


def _pdf_location(image: dict) -> PdfLocation | None:
    page, box = image.get("page"), _box(image.get("bbox"))
    if not isinstance(page, int) or isinstance(page, bool) or box is None:
        return None
    return PdfLocation(page, *box)


def _web_location(image: dict) -> WebLocation | None:
    raw = image.get("location")
    if not isinstance(raw, dict):
        return None
    page_file, xpath, box = raw.get("page_file"), raw.get("xpath"), _box(raw.get("bbox"))
    if not page_file or not isinstance(page_file, str) or not isinstance(xpath, str) or not box:
        return None
    return WebLocation(page_file, xpath, *box, str(image.get("id", "")))


def _web_key(image: dict) -> str:
    return image.get("unified_number") or image["id"]


def _skipped(row_id: str, key: str, image: dict, reason: str) -> ImagePair:
    return ImagePair(
        row_id=row_id,
        key=key,
        pdf_path=image["image_path"],
        web_path=None,
        skip_reason=reason,
        pdf_location=_pdf_location(image),
    )


def _matched_pair(row_id: str, number: str, image: dict, web: dict, web_key: str) -> ImagePair:
    web_path = web.get("local_path") or None
    reason = "" if web_path else "web image has no local file"
    return ImagePair(
        row_id=row_id,
        key=number,
        pdf_path=image["image_path"],
        web_path=web_path,
        web_key=web_key,
        skip_reason=reason,
        pdf_location=_pdf_location(image),
        web_location=_web_location(web),
    )


def _pdf_pair(image: dict, web_by_key: dict, counterparts: dict, used: set[str]) -> ImagePair:
    path = image["image_path"]
    row_id = f"pdf:{path}"
    number = image.get("unified_number")
    if not number:
        return _skipped(row_id, path, image, "no unified number")
    web_key = counterparts[number] if number in counterparts else number
    web = web_by_key.get(web_key) if web_key else None
    if web is None:
        return _skipped(row_id, number, image, "no web counterpart")
    used.add(web_key)
    return _matched_pair(row_id, number, image, web, web_key)


def _web_only_pair(image: dict) -> ImagePair:
    web_path = image.get("local_path") or None
    return ImagePair(
        row_id=f"web:{web_path or image['id']}",
        key=_web_key(image),
        pdf_path=None,
        web_path=web_path,
        web_key=_web_key(image),
        web_location=_web_location(image),
    )


def build_pairs(
    pdf_images: list[dict], web_images: list[dict], counterparts: dict[str, str | None]
) -> list[ImagePair]:
    web_by_key = {_web_key(image): image for image in web_images}
    used: set[str] = set()
    pairs = [_pdf_pair(image, web_by_key, counterparts, used) for image in pdf_images]
    pairs += [_web_only_pair(image) for image in web_images if _web_key(image) not in used]
    return pairs
