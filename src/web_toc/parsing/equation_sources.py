"""Collects every equation's real latex/mathml source from the site's own
content JSON, so the rendered formula image comes from the site's own
markup rather than a screenshot of one particular page's MathJax output. An
equation node can sit arbitrarily deep - inside a sentence's clauses, inside
a table cell - so this walks the whole JSON structure instead of assuming a
fixed shape. Pure: no file or browser I/O (see source_cache.py for the
file-loading wrapper)."""

from web_toc.domain.models import EquationSource


def _nodes_with_latex(value: object) -> list[dict]:
    if isinstance(value, dict):
        found = [value] if "latex" in value and "id" in value else []
        for child in value.values():
            found += _nodes_with_latex(child)
        return found
    if isinstance(value, list):
        return [node for item in value for node in _nodes_with_latex(item)]
    return []


def equation_sources_in_content(content: dict) -> dict[str, EquationSource]:
    """{node id: EquationSource} for every latex-bearing node in one page's
    content JSON, however deeply nested."""
    return {
        node["id"]: EquationSource(latex=node["latex"], mathml=node.get("mathml"))
        for node in _nodes_with_latex(content)
        if node["id"]
    }
