"""Whether a PDF leaf node and its web counterpart show the same content:
the same text apart from whitespace, with the same words in bold/italic -
see shared/styled_text.py for the rule itself.

The web renders a sentence/clause/subclause with its own "1)"/"a)"/"i)"
marker in front, where the PDF pipeline has already cut it off, so the
web's leading marker is dropped first - only when it is that node's own."""

import re

from shared.styled_text import StyledText, matches

_MARKED_TYPES = frozenset({"Sentence", "Clause", "Subclause"})
_LEADING_MARKER = re.compile(r"^\(?([0-9A-Za-z]{1,6})\)\s*")


def _styled(node: dict) -> StyledText:
    return StyledText.from_json(node.get("content", ""), node.get("emphasis"))


def _without_own_marker(node: dict, styled: StyledText) -> StyledText:
    if node.get("type") not in _MARKED_TYPES:
        return styled
    match = _LEADING_MARKER.match(styled.text)
    own_token = node.get("identifier", "").strip("()").lower()
    if not match or match.group(1).lower() != own_token:
        return styled
    return styled.slice(match.end())


def content_matches(pdf_node: dict, web_node: dict) -> bool:
    web = _without_own_marker(web_node, _styled(web_node))
    return matches(_styled(pdf_node), web)
