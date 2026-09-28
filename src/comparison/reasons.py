"""A reason for every failed text item and image, for comparison.json's
`reasons` and the viewer's "Why it differs" box. Only the items where a
difference actually is get one: a container's ✗ comes from an item inside
it, which the viewer says without a stored reason.

The text compared is the text the pass/fail rule compares (content_match),
and a table row or cell is compared with the web row or cell it was paired
with (`counterparts`)."""

from comparison.content_match import pdf_styled, web_styled
from comparison.difference import describe_difference
from comparison.engine import index_nodes


def _text_reason(pdf_node: dict, web_node: dict | None) -> dict:
    if web_node is None:
        return {"kind": "no_web"}
    difference = describe_difference(pdf_styled(pdf_node), web_styled(web_node))
    # Same text and bold/italic: the leaf failed on an image it holds.
    return difference or {"kind": "image_inside"}


def _leaves(node: dict):
    if not node.get("children"):
        yield node
    for child in node.get("children", []):
        yield from _leaves(child)


def _image_reasons(
    pdf_images: list[dict], web_images: list[dict], statuses: dict, counterparts: dict
) -> dict:
    on_site = {img.get("unified_number") for img in web_images}
    failed = (
        img["unified_number"]
        for img in pdf_images
        if statuses.get(img.get("unified_number")) is False
    )
    return {
        number: {
            "kind": "image_differs"
            if counterparts.get(number, number) in on_site
            else "no_web_image"
        }
        for number in failed
    }


def failure_reasons(
    pdf_tree: dict,
    pdf_images: list[dict],
    web_tree: dict | None,
    web_images: list[dict],
    statuses: dict[str, bool],
    counterparts: dict[str, str | None],
) -> dict[str, dict]:
    web_nodes: dict[str, dict] = {}
    if web_tree is not None:
        index_nodes(web_tree, web_nodes)
    reasons = {}
    for leaf in _leaves(pdf_tree):
        number = leaf.get("unified_number", "")
        if not number or statuses.get(number) is not False:
            continue
        web_number = counterparts.get(number, number)
        reasons[number] = _text_reason(leaf, web_nodes.get(web_number) if web_number else None)
    return reasons | _image_reasons(pdf_images, web_images, statuses, counterparts)
