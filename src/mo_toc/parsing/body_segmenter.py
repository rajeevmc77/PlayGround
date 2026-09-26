"""Splits an Article's accumulated body lines into Sentence -> Clause ->
Subclause nodes using the "1)"/"a)"/"i)" bracket-marker convention. Each body
line arrives paired with its 0-based page index (the same pairing
tree_builder.py accumulates per Article), since PageLine itself carries no
page number. A single roman-shaped letter (i, v, x, l, c, d, m) is ambiguous
between clause and subclause; resolved by, in priority order: (1) whether
it's the next expected clause letter in this sentence's own a, b, c...
sequence, (2) an x0-indent threshold splitting this sentence's confirmed
clause markers from its confirmed subclause markers, (3) same-page indent vs.
the immediately preceding clause, falling back to "clause" if nothing else
applies.
"""

import statistics

from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.marker_rules import RE_MARKER, classify_marker
from mo_toc.parsing.pdf_source import PageLine
from shared.styled_text import StyledText

BodyLine = tuple[int, PageLine]


def _split_into_sentence_groups(body_lines: list[BodyLine]) -> list[list[BodyLine]]:
    groups: list[list[BodyLine]] = []
    for page_index, pline in body_lines:
        match = RE_MARKER.match(pline.text)
        starts_sentence = match and classify_marker(match.group(1)) == "sentence"
        if starts_sentence:
            groups.append([(page_index, pline)])
        elif groups:
            groups[-1].append((page_index, pline))
    return groups


def _clause_subclause_x0s(group: list[BodyLine]) -> tuple[list[float], list[float]]:
    clause_x, subclause_x = [], []
    for _page_index, pline in group[1:]:
        match = RE_MARKER.match(pline.text)
        if not match:
            continue
        kind = classify_marker(match.group(1))
        if kind == "clause":
            clause_x.append(pline.x0)
        elif kind == "subclause":
            subclause_x.append(pline.x0)
    return clause_x, subclause_x


def _resolve_by_threshold(pline: PageLine, threshold: float) -> str:
    return "clause" if pline.x0 < threshold else "subclause"


def _resolve_by_proximity(pline: PageLine, prev_clause_x0: float | None) -> str:
    if prev_clause_x0 is not None and pline.x0 > prev_clause_x0 + 8:
        return "subclause"
    return "clause"


def _resolve_kind(kind, token, pline, next_letter, threshold, prev_clause_x0):
    if kind != "ambiguous":
        return kind
    if token.lower() == next_letter:
        return "clause"
    if threshold is not None:
        return _resolve_by_threshold(pline, threshold)
    return _resolve_by_proximity(pline, prev_clause_x0)


def _sentence_threshold(clause_x: list[float], subclause_x: list[float]) -> float | None:
    if not (clause_x and subclause_x):
        return None
    return (statistics.median(clause_x) + statistics.median(subclause_x)) / 2


def _advance_clause_state(pline: PageLine, token: str, next_letter: str) -> tuple[str, float]:
    if len(token) == 1:
        next_letter = chr(ord(token.lower()) + 1)
    return next_letter, pline.x0


def _marker_tail(pline: PageLine, match) -> StyledText:
    """The line's text after its "1)"/"a)"/"i)" marker, with its emphasis."""
    return pline.styled.slice(match.start(2))


def _marker_node(
    node_type: str,
    token: str,
    content: StyledText,
    parent_citation: str,
    page_index: int,
    pline,
    end_page: int,
) -> Node:
    identifier = f"({token.lower()})"
    page = page_index + 1
    return Node(
        type=node_type,
        identifier=identifier,
        citation=f"{parent_citation}{identifier}",
        title="",
        content=content.text,
        emphasis=list(content.emphasis),
        page=page,
        # end_page is inherited from the sentence/article boundary computed
        # before this marker's own page was known - clamp so it can't land
        # before this node's own start page (same class of bug as Fix 1).
        end_page=max(page, end_page),
        bbox=BBox(*pline.bbox),
    )


def _append_continuation(owner: Node, owner_start_page: int, page_index: int, pline) -> None:
    joined = StyledText(owner.content, tuple(owner.emphasis)).join(pline.styled)
    owner.content, owner.emphasis = joined.text, list(joined.emphasis)
    if page_index == owner_start_page:
        owner.bbox = owner.bbox.union(BBox(*pline.bbox))


def _add_clause(
    sentence: Node, match, page_index: int, pline, end_page: int, next_letter: str
) -> tuple[Node, str, float]:
    token, content = match.group(1), _marker_tail(pline, match)
    cur_clause = _marker_node(
        "Clause", token, content, sentence.citation, page_index, pline, end_page
    )
    sentence.children.append(cur_clause)
    next_letter, prev_clause_x0 = _advance_clause_state(pline, token, next_letter)
    return cur_clause, next_letter, prev_clause_x0


def _add_subclause(cur_clause: Node, match, page_index: int, pline, end_page: int) -> Node:
    token, content = match.group(1), _marker_tail(pline, match)
    subclause = _marker_node(
        "Subclause", token, content, cur_clause.citation, page_index, pline, end_page
    )
    cur_clause.children.append(subclause)
    return subclause


def _add_markers_to_sentence(sentence: Node, group: list[BodyLine], end_page: int) -> None:
    clause_x, subclause_x = _clause_subclause_x0s(group)
    threshold = _sentence_threshold(clause_x, subclause_x)
    next_letter, prev_clause_x0, cur_clause = "a", None, None
    current_owner, current_owner_page = sentence, sentence.page - 1

    for page_index, pline in group[1:]:
        match = RE_MARKER.match(pline.text)
        if not match:
            _append_continuation(current_owner, current_owner_page, page_index, pline)
            continue
        token, kind = match.group(1), classify_marker(match.group(1))
        kind = _resolve_kind(kind, token, pline, next_letter, threshold, prev_clause_x0)
        if kind == "clause":
            cur_clause, next_letter, prev_clause_x0 = _add_clause(
                sentence, match, page_index, pline, end_page, next_letter
            )
            current_owner, current_owner_page = cur_clause, page_index
            continue
        if kind != "subclause" or cur_clause is None:
            continue
        subclause = _add_subclause(cur_clause, match, page_index, pline, end_page)
        current_owner, current_owner_page = subclause, page_index


def _build_sentence(group: list[BodyLine], article_citation: str, end_page: int) -> Node:
    first_page_index, first_line = group[0]
    match = RE_MARKER.match(first_line.text)
    token, tail = match.group(1), _marker_tail(first_line, match)
    sentence = Node(
        type="Sentence",
        identifier=f"({token})",
        citation=f"{article_citation}({token})",
        title="",
        content=tail.text,
        emphasis=list(tail.emphasis),
        page=first_page_index + 1,
        end_page=end_page,
        bbox=BBox(*first_line.bbox),
    )
    _add_markers_to_sentence(sentence, group, end_page)
    return sentence


def segment_article_body(
    body_lines: list[BodyLine], article_citation: str, article_end_page: int
) -> list[Node]:
    groups = _split_into_sentence_groups(body_lines)
    sentences = [_build_sentence(g, article_citation, article_end_page) for g in groups]
    for i, sentence in enumerate(sentences):
        if i + 1 < len(sentences):
            sentence.end_page = sentences[i + 1].page
        else:
            # article_end_page is an inherited upper bound computed before
            # this (last) sentence's own page was known - clamp it the same
            # way _marker_node does, so it can't land before sentence.page.
            sentence.end_page = max(sentence.page, article_end_page)
    return sentences
