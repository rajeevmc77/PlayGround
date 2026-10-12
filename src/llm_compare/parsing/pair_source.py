"""Turns the PDF and web image indexes plus comparison.json's `counterparts` into one
ImagePair per report row: every PDF image, then every web image no PDF image pairs with."""

from llm_compare.domain.models import ImagePair


def _web_key(image: dict) -> str:
    return image.get("unified_number") or image["id"]


def _skipped(row_id: str, key: str, path: str, reason: str) -> ImagePair:
    return ImagePair(row_id=row_id, key=key, pdf_path=path, web_path=None, skip_reason=reason)


def _matched_pair(row_id: str, number: str, path: str, web: dict, web_key: str) -> ImagePair:
    web_path = web.get("local_path") or None
    reason = "" if web_path else "web image has no local file"
    return ImagePair(
        row_id=row_id,
        key=number,
        pdf_path=path,
        web_path=web_path,
        web_key=web_key,
        skip_reason=reason,
    )


def _pdf_pair(image: dict, web_by_key: dict, counterparts: dict, used: set[str]) -> ImagePair:
    path = image["image_path"]
    row_id = f"pdf:{path}"
    number = image.get("unified_number")
    if not number:
        return _skipped(row_id, path, path, "no unified number")
    web_key = counterparts[number] if number in counterparts else number
    web = web_by_key.get(web_key) if web_key else None
    if web is None:
        return _skipped(row_id, number, path, "no web counterpart")
    used.add(web_key)
    return _matched_pair(row_id, number, path, web, web_key)


def _web_only_pair(image: dict) -> ImagePair:
    web_path = image.get("local_path") or None
    return ImagePair(
        row_id=f"web:{web_path or image['id']}",
        key=_web_key(image),
        pdf_path=None,
        web_path=web_path,
        web_key=_web_key(image),
    )


def build_pairs(
    pdf_images: list[dict], web_images: list[dict], counterparts: dict[str, str | None]
) -> list[ImagePair]:
    web_by_key = {_web_key(image): image for image in web_images}
    used: set[str] = set()
    pairs = [_pdf_pair(image, web_by_key, counterparts, used) for image in pdf_images]
    pairs += [_web_only_pair(image) for image in web_images if _web_key(image) not in used]
    return pairs
