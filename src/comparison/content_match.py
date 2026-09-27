"""Whether a PDF leaf node and its web counterpart show the same content:
the same text apart from whitespace, with the same words in bold/italic -
see shared/styled_text.py for the rule itself.

The web renders a sentence/clause/subclause with its own "1)"/"a)"/"i)"
marker in front, where the PDF pipeline has already cut it off, so the
web's leading marker is dropped first - only when it is that node's own. A
note the same way: the web renders its identifier and title as its heading
in front of the body, where the PDF Note's content is the body alone."""

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


# How the site heads each node type's rendered text with its own identifier
# and title: "A-9.15.3.4.(2) Footing Sizes ...", "D-1.1.3. Applicability ...".
_OWN_HEADINGS = {"Note": "{identifier} {title}", "appendix_article": "{identifier}. {title}"}


def _without_own_heading(node: dict, styled: StyledText) -> StyledText:
    template = _OWN_HEADINGS.get(node.get("type", ""))
    if template is None:
        return styled
    heading = template.format(identifier=node.get("identifier", ""), title=node.get("title", ""))
    return styled.slice(len(heading)) if styled.text.startswith(heading) else styled


def pdf_styled(pdf_node: dict) -> StyledText:
    return _styled(pdf_node)


def web_styled(web_node: dict) -> StyledText:
    """The web node's text as it is compared: its own marker/heading dropped."""
    return _without_own_heading(web_node, _without_own_marker(web_node, _styled(web_node)))


def content_matches(pdf_node: dict, web_node: dict) -> bool:
    return matches(pdf_styled(pdf_node), web_styled(web_node))
