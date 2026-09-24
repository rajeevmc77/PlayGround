"""Pure string transforms that turn a scraped `main.ui-ContentPanel` into a
standalone page the viewer can show as-is.

The panel's own markup and the site's own CSS are kept untouched apart from:
the PDF-download header (its button only works inside the site's React
app), React's per-render `react-aria…` ids, root-relative image sources
(re-pointed at the local asset mirror), and the defined-term/cross-reference
info icon - the same ~560-byte SVG inlined once per term, 1000+ times on
some pages - which becomes one shared <symbol> plus a tiny <use> each.
Navigation links (`<a href="/code/…">`) are left alone for the viewer to
intercept.
"""

import html
import re

ASSET_PREFIX = "/web-assets"
INFO_ICON_ID = "bcbc-info-icon"

_HEADER_RE = re.compile(
    r'<div class="reading-view-header">[\s\S]*?'
    r'<div class="reading-view-header__divider" aria-hidden="true"></div></div>'
)
_REACT_ID_RE = re.compile(r' id="react-aria[^"]*"')
_ICON_RE = re.compile(
    r'(<span class="(?:glossary-term|cross-reference-link)__icon" aria-hidden="true">'
    r"<svg[^>]*>)([\s\S]*?)(</svg>)"
)
_VIEWBOX_RE = re.compile(r'viewBox="([^"]*)"')
_ROOT_SRC_RE = re.compile(r'src="(/(?!/)[^"]*)"')
# The site sizes its layout as 100vh minus its own header + breadcrumb bar;
# a saved page has neither, so the reading panel must fill the whole frame.
# The only override of the site's own CSS.
_NO_SITE_HEADER = "<style>:root{--header-height-full:0px}</style>"


def _dedupe_info_icons(panel: str) -> tuple[str, str]:
    first = _ICON_RE.search(panel)
    if first is None:
        return panel, ""
    viewbox = _VIEWBOX_RE.search(first.group(1))
    symbol = (
        '<svg style="display:none" aria-hidden="true">'
        f'<symbol id="{INFO_ICON_ID}" viewBox="{viewbox.group(1) if viewbox else ""}">'
        f"{first.group(2)}</symbol></svg>"
    )
    use = f'<use href="#{INFO_ICON_ID}"></use>'
    return _ICON_RE.sub(lambda m: f"{m.group(1)}{use}{m.group(3)}", panel), symbol


def clean_panel(panel: str) -> tuple[str, str]:
    """Returns (cleaned panel, shared icon <symbol> definition or "")."""
    panel = _HEADER_RE.sub("", panel)
    panel = _REACT_ID_RE.sub("", panel)
    panel = _ROOT_SRC_RE.sub(lambda m: f'src="{ASSET_PREFIX}{m.group(1)}"', panel)
    return _dedupe_info_icons(panel)


def image_paths(panel: str) -> list[str]:
    """Root-relative image sources, deduplicated in first-seen order."""
    return list(dict.fromkeys(_ROOT_SRC_RE.findall(panel)))


def compose_page(
    panel: str, stylesheets: list[str], inline_styles: list[str], icon_symbol: str, title: str
) -> str:
    links = "".join(f'<link rel="stylesheet" href="{ASSET_PREFIX}{href}">' for href in stylesheets)
    styles = "".join(f"<style>{css}</style>" for css in inline_styles)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>{links}{styles}{_NO_SITE_HEADER}</head>"
        f'<body>{icon_symbol}<main id="main-content">'
        f'<div class="MainLayout MainLayout--with-sidebar MainLayout--reading">{panel}'
        "</div></main></body></html>"
    )
