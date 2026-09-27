"""Builds an appendix's own structure from its content JSON - sections,
subsections, articles, and each article's numbered paragraphs - which the
site's navigation tree leaves out: Appendix D stops at the appendix itself,
so the PDF's "D-1.1.1." articles and their sentences had nothing to meet.

Numbers come from each level's position in its id ("appsect1.subsect1.
article3" -> "D-1.1.3"), the way the PDF prints them; a paragraph opening
with "1)" is a Sentence, as in the PDF, and one with no number is none
(the PDF's body segmenter keeps no unnumbered text either)."""

import re

from web_toc.domain.models import WebNode

_ORDINAL = re.compile(r"(\d+)$")
_PARAGRAPH_NUMBER = re.compile(r"^(\d+)\)\s")


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
