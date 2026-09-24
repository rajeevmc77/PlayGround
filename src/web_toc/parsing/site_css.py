"""Finds and re-points the url(...) references (fonts, background images)
inside the site's own stylesheets, so they can be mirrored locally.
"""

import posixpath
import re

from web_toc.parsing.page_html import ASSET_PREFIX

_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def _resolve(ref: str, css_path: str) -> str | None:
    if ref.startswith(("data:", "http:", "https:", "//", "#")):
        return None
    if ref.startswith("/"):
        return ref
    return posixpath.normpath(posixpath.join(posixpath.dirname(css_path), ref))


def css_url_paths(css: str, css_path: str) -> list[str]:
    """Site-root paths of every local asset `css` references, first-seen order."""
    resolved = (_resolve(m.group(2), css_path) for m in _URL_RE.finditer(css))
    return list(dict.fromkeys(path for path in resolved if path))


def rebase_css_urls(css: str, css_path: str) -> str:
    def replace(match: re.Match) -> str:
        path = _resolve(match.group(2), css_path)
        return f'url("{ASSET_PREFIX}{path}")' if path else match.group(0)

    return _URL_RE.sub(replace, css)


def build_nav_css(rules: list[dict]) -> str:
    """One standalone stylesheet from CSSOM-extracted {href, css} rules, each
    rebased against the stylesheet it came from, exact duplicates dropped."""
    rebased = (rebase_css_urls(rule["css"], rule["href"]) for rule in rules)
    return "".join(f"{css}\n" for css in dict.fromkeys(rebased))
