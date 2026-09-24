from web_toc.parsing.page_html import (
    ASSET_PREFIX,
    INFO_ICON_ID,
    clean_panel,
    compose_page,
    image_paths,
)

_ICON_PATH = '<path d="M13 8C13 8.5Z" fill="white"></path>'
_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
    f'fill="none">{_ICON_PATH}</svg>'
)
_HEADER = (
    '<div class="reading-view-header"><div class="reading-view-header__actions">'
    '<button id="react-aria123-_r_2_">Download PDF</button></div>'
    '<div class="reading-view-header__divider" aria-hidden="true"></div></div>'
)


def _term(label):
    return (
        '<span class="glossary-term glossary-term--interactive">'
        f'<span class="glossary-term__icon" aria-hidden="true">{_ICON_SVG}</span>{label}</span>'
    )


def _xref(label):
    return (
        '<button type="button" class="cross-reference-link">'
        f'<span class="cross-reference-link__icon" aria-hidden="true">{_ICON_SVG}</span>'
        f'<span class="cross-reference-link__text">{label}</span></button>'
    )


def test_clean_panel_removes_the_pdf_download_header():
    html = f'<div class="reading-view">{_HEADER}<div class="reading-view__content">x</div></div>'
    panel, _ = clean_panel(html)
    assert panel == '<div class="reading-view"><div class="reading-view__content">x</div></div>'


def test_clean_panel_keeps_html_without_a_header_unchanged():
    html = '<div class="partRenderer"><h1 class="partTitle">Part 1</h1></div>'
    assert clean_panel(html) == (html, "")


def test_clean_panel_strips_react_generated_ids_but_keeps_citation_ids():
    html = '<button id="react-aria99-_r_0_">b</button><div id="nbc.divA.part1.sent1">s</div>'
    panel, _ = clean_panel(html)
    assert panel == '<button>b</button><div id="nbc.divA.part1.sent1">s</div>'


def test_clean_panel_swaps_every_info_icon_for_one_shared_symbol():
    panel, symbol = clean_panel(_term("building") + _xref("Table 1") + _term("occupancy"))
    assert _ICON_PATH not in panel
    assert panel.count(f'<use href="#{INFO_ICON_ID}"></use>') == 3
    assert symbol == (
        '<svg style="display:none" aria-hidden="true">'
        f'<symbol id="{INFO_ICON_ID}" viewBox="0 0 24 24">{_ICON_PATH}</symbol></svg>'
    )


def test_clean_panel_keeps_the_icon_svg_element_and_its_size_attributes():
    panel, _ = clean_panel(_term("building"))
    assert (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none"><use href="#{INFO_ICON_ID}"></use></svg></span>building'
    ) in panel


def test_clean_panel_points_root_relative_image_sources_at_the_asset_mirror():
    html = '<img class="figure-block__image" src="/bc-graphics/fig-1.jpg">'
    panel, _ = clean_panel(html)
    assert panel == f'<img class="figure-block__image" src="{ASSET_PREFIX}/bc-graphics/fig-1.jpg">'


def test_clean_panel_leaves_navigation_links_and_absolute_sources_alone():
    html = '<a href="/code/nbc.divA/1/1?version=2024">1.1</a><img src="https://cdn.example/x.png">'
    assert clean_panel(html)[0] == html


def test_image_paths_lists_each_root_relative_source_once_in_order():
    html = '<img src="/g/a.jpg"><img src="https://x/y.png"><img src="/g/b.jpg"><img src="/g/a.jpg">'
    assert image_paths(html) == ["/g/a.jpg", "/g/b.jpg"]


def test_image_paths_is_empty_without_images():
    assert image_paths("<p>text</p>") == []


def test_compose_page_links_mirrored_stylesheets_and_inline_styles_in_order():
    page = compose_page(
        panel='<main class="ui-ContentPanel">P</main>',
        stylesheets=["/_next/static/chunks/a.css", "/_next/static/chunks/b.css"],
        inline_styles=["mjx-c{}"],
        icon_symbol="<svg>S</svg>",
        title="1.1 General",
    )
    a_link = f'<link rel="stylesheet" href="{ASSET_PREFIX}/_next/static/chunks/a.css">'
    b_link = f'<link rel="stylesheet" href="{ASSET_PREFIX}/_next/static/chunks/b.css">'
    assert page.index(a_link) < page.index(b_link) < page.index("<style>mjx-c{}</style>")
    assert "<title>1.1 General</title>" in page


def test_compose_page_wraps_the_panel_in_the_site_layout_ancestors():
    page = compose_page(
        panel="<main>P</main>",
        stylesheets=[],
        inline_styles=[],
        icon_symbol="<svg>S</svg>",
        title="t",
    )
    assert (
        '<body><svg>S</svg><main id="main-content">'
        '<div class="MainLayout MainLayout--with-sidebar MainLayout--reading"><main>P</main>'
        "</div></main></body>"
    ) in page


def test_compose_page_zeroes_the_site_header_height_after_the_site_styles():
    # The site sizes its reading panel as 100vh minus its own header and
    # breadcrumb bar; a saved page has neither, so the panel must fill the frame.
    page = compose_page(
        panel="", stylesheets=["/a.css"], inline_styles=["x{}"], icon_symbol="", title="t"
    )
    override = "<style>:root{--header-height-full:0px}</style>"
    assert page.index("<style>x{}</style>") < page.index(override) < page.index("</head>")


def test_compose_page_escapes_the_title():
    page = compose_page(panel="", stylesheets=[], inline_styles=[], icon_symbol="", title="A & <B>")
    assert "<title>A &amp; &lt;B&gt;</title>" in page
