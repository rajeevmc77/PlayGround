"""Walks one section/appendix/front-matter-article content JSON for
{"type": "sentence", ...} nodes and builds a Sentence -> Clause -> Subclause
WebNode subtree per sentence found - mirroring mo_toc's own body-text shape
and identifier conventions (a Sentence's own display number, a Clause's own
letter, a Subclause's own lowercase roman numeral, each wrapped in
parens). A sentence's clauses/subclauses are nested directly under its own
"clauses"/"subclauses" keys in the source JSON, so - unlike tables/figures -
no separate walk or owner resolution is needed for them; only the sentence
itself needs the strip-and-match owner resolution image_extractor.py and
table_extractor.py also use, since a sentence can sit arbitrarily deep
(e.g. nested inside a table cell).
"""

from web_toc.domain.models import WebNode
from web_toc.parsing.owner_resolution import attach_owned_nodes, resolve_owner

_ROMAN_NUMERALS = (
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)


def _lower_roman(number: int) -> str:
    result = []
    for value, numeral in _ROMAN_NUMERALS:
        count, number = divmod(number, value)
        result.append(numeral * count)
    return "".join(result)


def _subclause_node(subclause: dict) -> WebNode:
    identifier = f"({_lower_roman(subclause.get('number', 0))})"
    return WebNode(
        type="Subclause",
        identifier=identifier,
        citation=subclause.get("id", ""),
        title="",
        path="",
        content=subclause.get("text", ""),
    )


def _clause_node(clause: dict) -> WebNode:
    identifier = f"({clause.get('letter', '')})"
    return WebNode(
        type="Clause",
        identifier=identifier,
        citation=clause.get("id", ""),
        title="",
        path="",
        content=clause.get("text", ""),
        children=[_subclause_node(sc) for sc in clause.get("subclauses", []) if sc.get("id")],
    )


def _sentence_node(sentence: dict) -> WebNode:
    identifier = f"({sentence.get('number', '')})"
    return WebNode(
        type="Sentence",
        identifier=identifier,
        citation=sentence["id"],
        title="",
        path="",
        content=sentence.get("text", ""),
        children=[_clause_node(c) for c in sentence.get("clauses", []) if c.get("id")],
    )


def _walk_sentences(node):
    if isinstance(node, dict):
        if node.get("type") == "sentence":
            # Its own clauses/subclauses are built directly from its nested
            # keys above, not walked separately - stop descending here.
            yield node
            return
        for value in node.values():
            yield from _walk_sentences(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_sentences(item)


def extract_body(
    content: dict, citations: set[str], fallback_citation: str
) -> list[tuple[str, WebNode]]:
    owned_sentences = []
    for sentence in _walk_sentences(content):
        sentence_id = sentence.get("id")
        if sentence_id is None:
            continue
        owner = resolve_owner(sentence_id, citations, fallback_citation)
        owned_sentences.append((owner, _sentence_node(sentence)))
    return owned_sentences


def attach_body(root: WebNode, owned_sentences: list[tuple[str, WebNode]]) -> None:
    attach_owned_nodes(root, owned_sentences)
