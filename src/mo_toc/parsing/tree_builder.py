"""Walks every page of a PdfSource, classifying each line as a heading, a Note
entry, a Table/Figure caption, or plain body text, and assembles the Volume
tree via a rank-based open-node stack: a new heading at rank R closes every
currently-open node whose own rank is >= R, then nests under whatever is left
open (the same "closing tag" logic an XML/HTML parser uses for nested elements
with implicit closes). A heading's or caption's own title is not always on the
same physical line: a long title can wrap onto a further same-weight line, or
even a separate PDF layout block (confirmed: "Part 1" and "Compliance" render
as two separate Arial-Black blocks) - so after recognizing a heading/caption
trigger line, subsequent same-weight lines are folded into its title until a
new heading/caption of its own is hit, with one override (mirrors the
archived analysis): a heading-shaped continuation line is still folded in if
the title captured so far trails off on "and"/"or".
"""

import re
from dataclasses import dataclass, field

from mo_toc.domain.models import BBox, Caption, Node
from mo_toc.parsing.body_segmenter import segment_article_body
from mo_toc.parsing.heading_rules import (
    ARTICLE_TYPES,
    RANK,
    classify_caption_line,
    classify_heading_line,
)
from mo_toc.parsing.pdf_source import PageLine, PdfSource

RE_NOTE_ENTRY = re.compile(r"^([A-Z]-\S+(?:\s+(?:and|to)\s+\(\d+\))*)\s+(.*)$")
RE_ENDS_WITH_CONJUNCTION = re.compile(r"\b(?:and|or)\s*$", re.IGNORECASE)


@dataclass
class _BuildState:
    stack: list
    division: str | None = None
    in_notes: bool = False
    seen_structure: bool = False
    current_article: Node | None = None
    article_bodies: dict = field(default_factory=dict)
    captions: list = field(default_factory=list)


def _citation_for(ntype: str, match, division: str | None) -> tuple[str, str, str]:
    if ntype == "Division":
        return match.group(1), "", match.group(1)
    if ntype == "Part":
        return match.group(1), "", f"{division}-{match.group(1)}"
    if ntype == "NotesContainer":
        return match.group(1), "", f"Notes-{division}-{match.group(1)}"
    if ntype in ("Section", "Article", "Subsection"):
        ident = match.group(1) + "."
        return ident, match.group(2).strip(), f"{division}-{ident}"
    if ntype == "Appendix":
        return match.group(1), "", f"Appendix-{match.group(1)}"
    if ntype == "AppendixPart":
        ident = f"{match.group(1)}-{match.group(2)}"
        return ident, match.group(3).strip(), f"Appendix-{ident}"
    if ntype in ("AppendixSection", "AppendixArticle"):
        ident = f"{match.group(1)}-{match.group(2)}."
        return ident, match.group(3).strip(), f"Appendix-{ident}"
    if ntype == "TableGroup":
        ident = match.group(0).strip()
        return ident, "", f"{division}-{ident}"
    return "BackMatter", "", "BackMatter"


def _consume_heading_title(lines: list[PageLine], idx: int, title: str) -> tuple[str, int]:
    """BackMatter's own trigger line (Arial-BoldMT) has no meaningful title to
    fold - every other heading type is Arial-Black-gated, so continuation
    lines are recognized the same way regardless of which specific type
    triggered this call.
    """
    while idx < len(lines) and "Black" in lines[idx].font:
        text = lines[idx].text
        heading_here = classify_heading_line(text, lines[idx].font)
        dangling = bool(RE_ENDS_WITH_CONJUNCTION.search(title.strip()))
        if heading_here is not None and not dangling:
            break
        title = (title + " " + text).strip()
        idx += 1
    return title, idx


def _open_node(
    ntype: str, match, page_index: int, lines: list[PageLine], idx: int, state: _BuildState
) -> int:
    identifier, title, citation = _citation_for(ntype, match, state.division)
    bbox = BBox(*lines[idx].bbox)
    next_idx = idx + 1
    if ntype == "Division":
        state.division = identifier
    if ntype != "BackMatter":
        title, next_idx = _consume_heading_title(lines, next_idx, title)

    rank = RANK[ntype]
    while len(state.stack) > 1 and state.stack[-1][0] >= rank:
        state.stack.pop()
    parent = state.stack[-1][1]
    node = Node(
        type=ntype,
        identifier=identifier,
        citation=citation,
        title=title,
        page=page_index + 1,
        end_page=page_index + 1,
        bbox=bbox,
    )
    parent.children.append(node)
    state.stack.append((rank, node))
    if rank <= 2:
        state.in_notes = ntype == "NotesContainer"
    if ntype in ("Division", "Appendix"):
        state.seen_structure = True
    state.current_article = node if ntype in ARTICLE_TYPES else None
    if ntype in ARTICLE_TYPES:
        state.article_bodies[id(node)] = []
    return next_idx


def _open_note(match, page_index: int, bbox: BBox, state: _BuildState) -> None:
    identifier, title = match.group(1).rstrip("."), match.group(2).strip()
    node = Node(
        type="Note",
        identifier=identifier,
        citation=f"Note:{identifier}",
        title=title,
        page=page_index + 1,
        end_page=page_index + 1,
        bbox=bbox,
    )
    state.stack[-1][1].children.append(node)
    state.current_article = None


def _consume_caption_title(lines: list[PageLine], idx: int) -> tuple[str, int]:
    parts = []
    while idx < len(lines) and len(parts) < 3:
        text, font = lines[idx].text, lines[idx].font
        is_caption_font = "Bold" in font and "Black" not in font and "Narrow" not in font
        if not is_caption_font:
            break
        if classify_heading_line(text, font) or classify_caption_line(text, font):
            break
        parts.append(text)
        idx += 1
    return " ".join(parts).strip(), idx


def _open_caption(
    match, page_index: int, lines: list[PageLine], idx: int, state: _BuildState
) -> int:
    bbox = BBox(*lines[idx].bbox)
    title, next_idx = _consume_caption_title(lines, idx + 1)
    owner = state.stack[-1][1].citation if len(state.stack) > 1 else ""
    state.captions.append(
        Caption(
            kind=match.group(1),
            identifier=match.group(2).strip(),
            title=title,
            page=page_index + 1,
            bbox=bbox,
            owner_citation=owner,
            forming_part_of=None,
            continuation=False,
        )
    )
    return next_idx


def _process_page(lines: list[PageLine], page_index: int, state: _BuildState) -> None:
    idx = 0
    while idx < len(lines):
        pline = lines[idx]
        cap_match = classify_caption_line(pline.text, pline.font)
        if cap_match:
            idx = _open_caption(cap_match, page_index, lines, idx, state)
            continue
        heading = classify_heading_line(pline.text, pline.font)
        if heading and heading[0] == "BackMatter" and not state.seen_structure:
            heading = None
        if heading:
            idx = _open_node(heading[0], heading[1], page_index, lines, idx, state)
            continue
        if state.in_notes:
            note_match = RE_NOTE_ENTRY.match(pline.text)
            if note_match:
                _open_note(note_match, page_index, BBox(*pline.bbox), state)
                idx += 1
                continue
        if state.current_article is not None:
            state.article_bodies[id(state.current_article)].append((page_index, pline))
        idx += 1


def _finalize_end_pages(node: Node, last_page: int) -> None:
    for i, child in enumerate(node.children):
        child.end_page = node.children[i + 1].page - 1 if i + 1 < len(node.children) else last_page
        _finalize_end_pages(child, child.end_page)


def _iter_nodes(node: Node):
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def build_tree(source: PdfSource) -> tuple[Node, list[Caption]]:
    volume = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=source.page_count,
        bbox=BBox(0, 0, 0, 0),
    )
    front_matter = Node(
        type="FrontMatter",
        identifier="FrontMatter",
        citation="FrontMatter",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    volume.children.append(front_matter)
    state = _BuildState(stack=[(0, volume), (1, front_matter)])

    for page_index in range(source.page_count):
        _process_page(source.page_lines(page_index), page_index, state)

    _finalize_end_pages(volume, source.page_count)
    for node_id, body in state.article_bodies.items():
        article = next(n for n in _iter_nodes(volume) if id(n) == node_id)
        article.children = segment_article_body(body, article.citation, article.end_page)
    return volume, state.captions
