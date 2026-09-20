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


def _resolve_kind(kind, token, pline, next_letter, threshold, prev_clause_x0):
    if kind != "ambiguous":
        return kind
    if token.lower() == next_letter:
        return "clause"
    if threshold is not None:
        return "clause" if pline.x0 < threshold else "subclause"
    if prev_clause_x0 is not None and pline.x0 > prev_clause_x0 + 8:
        return "subclause"
    return "clause"


def _build_sentence(group: list[BodyLine], article_citation: str, end_page: int) -> Node:
    first_page_index, first_line = group[0]
    token = RE_MARKER.match(first_line.text).group(1)
    sentence = Node(type="Sentence", identifier=f"({token})",
                     citation=f"{article_citation}({token})",
                     title=first_line.text,
                     page=first_page_index + 1, end_page=end_page, bbox=BBox(*first_line.bbox))

    clause_x, subclause_x = _clause_subclause_x0s(group)
    threshold = ((statistics.median(clause_x) + statistics.median(subclause_x)) / 2
                 if clause_x and subclause_x else None)
    next_letter, prev_clause_x0, cur_clause = "a", None, None

    for page_index, pline in group[1:]:
        match = RE_MARKER.match(pline.text)
        if not match:
            continue
        token, kind = match.group(1), classify_marker(match.group(1))
        kind = _resolve_kind(kind, token, pline, next_letter, threshold, prev_clause_x0)
        if kind == "clause":
            cur_clause = Node(type="Clause", identifier=f"({token.lower()})",
                               citation=f"{sentence.citation}({token.lower()})",
                               title=pline.text,
                               page=page_index + 1, end_page=end_page, bbox=BBox(*pline.bbox))
            sentence.children.append(cur_clause)
            prev_clause_x0 = pline.x0
            if len(token) == 1:
                next_letter = chr(ord(token.lower()) + 1)
        elif kind == "subclause" and cur_clause is not None:
            subclause = Node(type="Subclause", identifier=f"({token.lower()})",
                              citation=f"{cur_clause.citation}({token.lower()})",
                              title=pline.text,
                              page=page_index + 1, end_page=end_page, bbox=BBox(*pline.bbox))
            cur_clause.children.append(subclause)
    return sentence


def segment_article_body(body_lines: list[BodyLine], article_citation: str,
                          article_end_page: int) -> list[Node]:
    groups = _split_into_sentence_groups(body_lines)
    sentences = [_build_sentence(g, article_citation, article_end_page) for g in groups]
    for i, sentence in enumerate(sentences):
        sentence.end_page = (sentences[i + 1].page if i + 1 < len(sentences)
                              else article_end_page)
    return sentences
