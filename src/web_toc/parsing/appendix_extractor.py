"""Builds an appendix's own structure from its content JSON - sections,
subsections, articles, and each article's numbered paragraphs - which the
site's navigation tree leaves out: Appendix D stops at the appendix itself,
so the PDF's "D-1.1.1." articles and their sentences had nothing to meet.

Numbers come from each level's position in its id ("appsect1.subsect1.
article3" -> "D-1.1.3"), the way the PDF prints them; a paragraph opening
with "1)" is a Sentence, as in the PDF, and one with no number is none
(the PDF's body segmenter keeps no unnumbered text either). A Sentence's
lettered list items are its Clauses (a), (b), ...; they have no ids, so
each is cited by its position, "<paragraph id>.li2" - and a clause's own
nested items are its Subclauses, "<paragraph id>.li2.li1"."""

import re
from collections.abc import Iterator

from web_toc.domain.models import WebNode
from web_toc.parsing.body_extractor import lower_roman

_ORDINAL = re.compile(r"(\d+)$")
_PARAGRAPH_NUMBER = re.compile(r"^(\d+)\)\s")
# The list types the site renders as a lettered <ol> - a sentence's clauses;
# a "variable" list ("where t = ...") is a <dl>.
_LETTERED_LISTS = frozenset({"bulleted", "alphabetic"})
_LIST_PLACEHOLDER = re.compile(r"\[LIST:\w+\]")


def _ordinal(item: dict) -> str:
    match = _ORDINAL.search(item.get("id", ""))
    return match.group(1) if match else ""


def _node(item: dict, type_: str, identifier: str, heading: str, children) -> WebNode:
    return WebNode(
        type=type_,
        identifier=identifier,
        citation=item["id"],
        title=item.get("title", ""),
        path="",
        heading=heading,
        children=children,
    )


def _list_item_node(type_: str, identifier: str, citation: str, item: dict, children):
    return WebNode(
        type=type_,
        identifier=f"({identifier})",
        citation=citation,
        title="",
        path="",
        content=item.get("content", ""),
        children=children,
    )


def _lettered_items(content, lists: Iterator[dict]) -> list[tuple[dict, list]]:
    """The lettered list items `content`'s "[LIST:...]" placeholders stand
    for, each with its own nested items. The JSON flattens nested lists: a
    paragraph's `lists` holds, in document order, the list each placeholder -
    its own, then those inside its items - stands for."""
    items = []
    for _placeholder in _LIST_PLACEHOLDER.findall(content if isinstance(content, str) else ""):
        lst = next(lists, {})
        nested = [
            (item, _lettered_items(item.get("content"), lists)) for item in lst.get("items", [])
        ]
        items.extend(nested if lst.get("type") in _LETTERED_LISTS else [])
    return items


def _subclauses(clause_citation: str, items: list[tuple[dict, list]]) -> list[WebNode]:
    return [
        _list_item_node("Subclause", lower_roman(i + 1), f"{clause_citation}.li{i + 1}", item, [])
        for i, (item, _nested) in enumerate(items)
    ]


def _clauses(paragraph: dict) -> list[WebNode]:
    """The paragraph's lettered list items, cited by their position the way
    the layout lists them (layout_join._list_item_entry) - "<para>.li2", and
    a clause's own nested items "<para>.li2.li1" are its subclauses."""
    items = _lettered_items(paragraph.get("content"), iter(paragraph.get("lists", [])))
    clauses = []
    for i, (item, nested) in enumerate(items):
        citation = f"{paragraph['id']}.li{i + 1}"
        letter = chr(ord("a") + i)
        clauses.append(
            _list_item_node("Clause", letter, citation, item, _subclauses(citation, nested))
        )
    return clauses


def _sentence(paragraph: dict) -> WebNode | None:
    text = paragraph.get("content")
    match = _PARAGRAPH_NUMBER.match(text) if isinstance(text, str) else None
    if match is None:
        return None
    return WebNode(
        type="Sentence",
        identifier=f"({match.group(1)})",
        citation=paragraph["id"],
        title="",
        path="",
        content=text,
        children=_clauses(paragraph),
    )


def _article(article: dict, number: str) -> WebNode:
    paragraphs = (c for c in article.get("content", []) if c.get("type") == "paragraph")
    sentences = [s for s in map(_sentence, paragraphs) if s is not None]
    return _node(article, "appendix_article", number, f"{number}.", sentences)


def _subsection(subsection: dict, number: str) -> WebNode:
    articles = [_article(a, f"{number}.{_ordinal(a)}") for a in subsection.get("articles", [])]
    return _node(subsection, "appendix_subsection", number, f"{number}.", articles)


def _section(section: dict, number: str) -> WebNode:
    subsections = [
        _subsection(s, f"{number}.{_ordinal(s)}") for s in section.get("subsections", [])
    ]
    return _node(section, "appendix_section", number, f"Section {number}", subsections)


def extract_appendix(content: dict, owner_citation: str) -> list[tuple[str, WebNode]]:
    if content.get("type") != "appendix":
        return []
    letter = content.get("letter", "")
    # Appendix C's "sections" are note divisions, with no numbered
    # structure in the PDF to meet.
    sections = (s for s in content.get("sections", []) if s.get("type") == "appendix_section")
    return [(owner_citation, _section(s, f"{letter}-{_ordinal(s)}")) for s in sections]
