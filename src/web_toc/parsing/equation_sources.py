"""Collects every equation's real latex/mathml source from the site's own
content JSON, so the rendered formula image comes from the site's own
markup rather than a screenshot of one particular page's MathJax output. An
equation node can sit arbitrarily deep - inside a sentence's clauses, inside
a table cell - so this walks the whole JSON structure instead of assuming a
fixed shape. Pure: no file or browser I/O (see source_cache.py for the
file-loading wrapper)."""

from web_toc.domain.models import EquationSource


def _is_equation_node(node: dict) -> bool:
    return "id" in node and ("latex" in node or "plainText" in node)


def _latex_of(node: dict) -> str:
    """A node with neither latex nor mathml (AppC's ex000108q1/q2) is
    typeset by the site from its plainText, read as TeX."""
    return node["latex"] if "latex" in node else node["plainText"]


def _walk_dict(node: dict) -> list[dict]:
    found = [node] if _is_equation_node(node) else []
    for child in node.values():
        found += _nodes_with_latex(child)
    return found


def _walk_list(items: list) -> list[dict]:
    return [node for item in items for node in _nodes_with_latex(item)]


def _nodes_with_latex(value: object) -> list[dict]:
    if isinstance(value, dict):
        return _walk_dict(value)
    if isinstance(value, list):
        return _walk_list(value)
    return []


def equation_sources_in_content(content: dict) -> dict[str, EquationSource]:
    """{node id: EquationSource} for every latex- (or plainText-) bearing node in one page's
    content JSON, however deeply nested."""
    return {
        node["id"]: EquationSource(latex=_latex_of(node), mathml=node.get("mathml"))
        for node in _nodes_with_latex(content)
        if node["id"]
    }
