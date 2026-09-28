"""Pairs a provision's PDF images with its web images by where they stand,
when the two sides label them differently.

Images are keyed `<provision>.FigN` / `.EqN`, counted separately per label.
The PDF reads an uncaptioned image as an equation by its shape; the site
knows which of its images are MathJax formulas. Where the two disagree -
4.1.6.5.'s stacked two-line formula is a figure in the PDF, an equation on
the site - every image after it met the wrong partner by number. Here a
provision's images outside tables, when both sides have as many, pair in
the order they stand on the page, whatever their labels; a table's images,
and a provision with more images on one side, keep their numbers. Images
never pair across provisions. Pure: dicts in, dict out."""

import re
from collections import defaultdict

_LABEL = re.compile(r"\.(?:Fig|Eq)\d+$")
_WEB_TABLE_IMAGE = re.compile(r"\.table\d+(?:\.|$)")


def _provision(image: dict) -> str:
    return _LABEL.sub("", image["unified_number"])


def _cells_by_page(node: dict, into: dict[int, list[dict]]) -> dict[int, list[dict]]:
    if node.get("type") == "Cell" and node.get("bbox"):
        into[node.get("page")].append(node["bbox"])
    for child in node.get("children", []):
        _cells_by_page(child, into)
    return into


def _in_a_cell(image: dict, cells_by_page: dict[int, list[dict]]) -> bool:
    box = image["bbox"]
    x, y = (box["x0"] + box["x1"]) / 2, (box["y0"] + box["y1"]) / 2
    cells = cells_by_page.get(image.get("page"), [])
    return any(c["x0"] <= x <= c["x1"] and c["y0"] <= y <= c["y1"] for c in cells)


def _pdf_outside_tables(pdf_tree: dict, pdf_images: list[dict]) -> list[dict]:
    cells = _cells_by_page(pdf_tree, defaultdict(list))
    numbered = (image for image in pdf_images if image.get("unified_number") and image.get("bbox"))
    return [image for image in numbered if not _in_a_cell(image, cells)]


def _web_outside_tables(web_images: list[dict]) -> list[dict]:
    """A web image in a table carries its table in its id: "...table1.eg1"."""
    numbered = (image for image in web_images if image.get("unified_number"))
    return [image for image in numbered if not _WEB_TABLE_IMAGE.search(image.get("id", ""))]


def _pdf_position(image: dict) -> tuple:
    return image.get("page", 0), image["bbox"]["y0"], image["bbox"]["x0"]


def _web_position(image: dict) -> tuple:
    location = image.get("location") or {}
    box = location.get("bbox") or {}
    return location.get("page_file", ""), box.get("y0", 0), box.get("x0", 0)


def _by_provision(images: list[dict], position) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for image in images:
        grouped[_provision(image)].append(image)
    return {key: sorted(group, key=position) for key, group in grouped.items()}


def _changed_pairs(pdf_group: list[dict], web_group: list[dict]) -> dict[str, str]:
    if len(pdf_group) != len(web_group):
        return {}
    pairs = zip(pdf_group, web_group, strict=True)
    return {
        pdf["unified_number"]: web["unified_number"]
        for pdf, web in pairs
        if pdf["unified_number"] != web["unified_number"]
    }


def image_counterparts(
    pdf_tree: dict, pdf_images: list[dict], web_images: list[dict]
) -> dict[str, str]:
    """PDF image number -> the web image it pairs with, for every pairing
    that differs from the same-numbered one."""
    pdf_groups = _by_provision(_pdf_outside_tables(pdf_tree, pdf_images), _pdf_position)
    web_groups = _by_provision(_web_outside_tables(web_images), _web_position)
    counterparts: dict[str, str] = {}
    for provision, pdf_group in pdf_groups.items():
        counterparts.update(_changed_pairs(pdf_group, web_groups.get(provision, [])))
    return counterparts
