"""Enriches each extracted ImageAsset with where it lives in the document:
which node (Article, Note, Section, ...) its page falls under, and - when a
Table/Figure caption sits close enough to it on the same page - that
caption's own identifier, so an image can be shown as "Figure A-1.3.3.4.(2)"
rather than just "p.37" wherever a real caption exists for it.
"""

import dataclasses

from mo_toc.domain.models import Caption, ImageAsset, Node

MAX_CAPTION_GAP = 50.0  # pt; beyond this a caption is presumed unrelated

# pt, in the image's smaller dimension. Deliberately its own threshold, not
# the viewer's "hide decorative images" convention (mo_toc.domain.image_
# classification.is_decorative): that one lets a wide-but-short single-line
# formula through so it's still visible in the Table of Images, but such a
# formula must NOT become caption-eligible here - a caption never describes
# an inline equation, only a genuine Figure/Table, so this floor stays
# keyed on the smaller dimension alone (real-document regression: a 100x24pt
# equation glyph must not outrank a farther 300x250pt diagram for the same
# caption - see test_small_ineligible_image_does_not_steal_a_caption_from_a_
# farther_real_figure).
MIN_CAPTION_ELIGIBLE_DIM = 40.0

# Table/Row/Cell are never pushed as position-walkable owners - an image is
# never attributed to a specific table cell, matching how images are never
# themselves parsed as table content. Sentence/Clause/Subclause, by
# contrast, ARE valid owners now that body_segmenter gives them accurate
# per-node bboxes - an inline formula image inside a single Clause resolves
# to that Clause, not the enclosing Article.
_NON_OWNER_TYPES = {"Table", "Row", "Cell"}


def _structural_children(node: Node) -> list[Node]:
    return [c for c in node.children if c.type not in _NON_OWNER_TYPES]


def _best_child(node: Node, image: ImageAsset) -> Node | None:
    """The child whose own heading most recently opened at or before the
    image's position, in (page, y0) reading order - the same "currently
    open" rule the live tree walk uses for captions, reconstructed here from
    position alone. Deliberately ignores end_page: it's a lossy page-level
    projection of "until the next sibling opens" (confirmed on the real
    document: several same-page Notes routinely get end_page clamped to
    their own start page, which would wrongly exclude a genuine owner whose
    content spills onto the next page before the next Note begins) - the
    next sibling's own start position is the real boundary, not end_page.
    """
    target = (image.page, image.bbox.y0)
    preceding = [c for c in _structural_children(node) if (c.page, c.bbox.y0) <= target]
    if not preceding:
        return None
    return max(preceding, key=lambda c: (c.page, c.bbox.y0))


def _deepest_owner(node: Node, image: ImageAsset) -> Node:
    child = _best_child(node, image)
    if child is None:
        return node
    return _deepest_owner(child, image)


def assign_owner(image: ImageAsset, volume: Node) -> str:
    return _deepest_owner(volume, image).citation


def _gap(image: ImageAsset, caption: Caption) -> float | None:
    """Vertical distance between the two closer edges, whichever pairing
    that is - not just "cleanly below" or "cleanly above". Real captions
    routinely sit within ~1pt of the image's own edge, or even overlap it
    by a hair (font-leading/whitespace measurement slop), so a strict
    non-overlap check misses the obviously-correct pairing.
    """
    if caption.page != image.page:
        return None
    return min(
        abs(caption.bbox.y0 - image.bbox.y1),
        abs(image.bbox.y0 - caption.bbox.y1),
    )


def _kind_rank(caption: Caption) -> int:
    """Embedded images are never themselves data tables - tables in this
    document are parsed as text, never as an image - so a Figure-kind
    caption in range is always the semantically correct pick over a Table
    caption, even one that happens to sit a little closer (e.g. a Table
    caption introducing unrelated text content right after the figure)."""
    return 0 if caption.kind == "Figure" else 1


def _is_caption_eligible(image: ImageAsset) -> bool:
    width = image.bbox.x1 - image.bbox.x0
    height = image.bbox.y1 - image.bbox.y0
    return min(width, height) >= MIN_CAPTION_ELIGIBLE_DIM


def _nearest_caption(image: ImageAsset, captions: list[Caption]) -> Caption | None:
    candidates = []
    for caption in captions:
        gap = _gap(image, caption)
        if gap is not None and gap <= MAX_CAPTION_GAP:
            candidates.append((_kind_rank(caption), gap, caption))
    if not candidates:
        return None
    return min(candidates, key=lambda triple: triple[:2])[2]


def _claim_caption(image: ImageAsset, captions: list[Caption], claimed_ids: set) -> Caption | None:
    if not _is_caption_eligible(image):
        return None
    available = [c for c in captions if id(c) not in claimed_ids]
    caption = _nearest_caption(image, available)
    if caption is not None:
        claimed_ids.add(id(caption))
    return caption


def match_images(
    images: list[ImageAsset], captions: list[Caption], volume: Node
) -> list[ImageAsset]:
    claimed_ids = set()
    enriched = []
    for image in images:
        owner_citation = assign_owner(image, volume)
        caption = _claim_caption(image, captions, claimed_ids)
        title = f"{caption.kind} {caption.identifier}" if caption else ""
        enriched.append(
            dataclasses.replace(
                image,
                owner_citation=owner_citation,
                caption_kind=caption.kind if caption else None,
                caption_identifier=caption.identifier if caption else None,
                caption_title=caption.title if caption else None,
                title=title,
            )
        )
    return enriched
