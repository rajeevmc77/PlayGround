"""Drives a real headless Chromium against local file:// fixture pages -
no network - so the scraping contract (what gets captured, when a page
counts as not rendered) is pinned without depending on the live site."""

import asyncio

import pytest

from web_toc.parsing.page_source import PlaywrightPageSource

_SITE_PAGE = """<!DOCTYPE html><html><head><title>Section 1 - BC Building Code</title>
<link rel="stylesheet" href="/_next/static/chunks/a.css">
<style>.mjx-c{color:red}</style></head><body>
<main id="main-content"><div class="MainLayout">
<aside class="ui-Sidebar">tree</aside>
<main class="ui-ContentPanel"><div class="reading-view__content"><h1 class="partTitle">Part 1</h1>
</div></main></div></main></body></html>"""

_UNRENDERED_PAGE = """<!DOCTYPE html><html><head><title>403 Forbidden</title></head>
<body><h1>403 Forbidden</h1></body></html>"""

_NAV_CSS_PAGE = """<!DOCTYPE html><html><head><style>
.nav-tree-link{color:#2d2d2d}
.unrelated{color:red}
@media (min-width:48rem){.breadcrumbs-title{max-width:120px}}
:root{--theme-primary-blue:#013366}
@font-face{font-family:BC Sans;src:url(../media/f.woff2)}
</style></head><body><main class="ui-ContentPanel"><div class="partRenderer"></div></main>
</body></html>"""


# Mimics the live site's long tables: 5 rows at first, 5 more appended
# (asynchronously) each time the last row scrolls into view, up to 23 -
# inside a panel that is itself the scroll container.
_LAZY_TABLE_PAGE = """<!DOCTYPE html><html><head><title>Lazy</title></head><body>
<main id="main-content"><div class="MainLayout">
<main class="ui-ContentPanel" style="display:block;height:300px;overflow:auto">
<div class="reading-view__content"><div id="t1"><table><tbody></tbody></table></div>
</div></main></div></main>
<script>
const body = document.querySelector('#t1 tbody');
let total = 0;
const observer = new IntersectionObserver((entries) => {
  if (!entries.some((e) => e.isIntersecting)) return;
  setTimeout(addRows, 50);
});
function addRows() {
  const last = body.lastElementChild;
  if (last) observer.unobserve(last);
  for (let i = 0; i < 5 && total < 23; i++, total++) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td style="height:80px">row ${total + 1}</td>`;
    body.appendChild(tr);
  }
  if (total < 23) observer.observe(body.lastElementChild);
}
addRows();
</script></body></html>"""


_SPLIT_TABLE_PAGE = """<!DOCTYPE html><html><head><title>Split</title></head><body>
<main id="main-content"><div class="MainLayout"><main class="ui-ContentPanel">
<div class="reading-view__content"><div id="wide">
<table class="table-block__table--split-header"><tr><th>H</th></tr></table>
<table class="table-block__table--split-header table-block__table--pinned-col"><tr><th>H</th></tr>
</table><table class="table-block__table--split-body"><tr><td>a<table><tr><td>n</td></tr></table>
</td></tr><tr><td>b</td></tr></table></div></div></main></div></main></body></html>"""


def _tr_count(page):
    return page.panel.count("<tr")


async def _scrape_all(urls, nav_url, lazy_url, split_url):
    async with PlaywrightPageSource(ready_timeout_ms=1500, growth_timeout_ms=400) as source:
        pages = {key: await source.fetch_page(url) for key, url in urls.items()}
        nav_all = await source.fetch_nav_css(nav_url, r"nav-tree|breadcrumbs")
        nav_tree_only = await source.fetch_nav_css(nav_url, r"nav-tree")
        pages["lazy_complete"] = await source.fetch_page(lazy_url, {"t1": 23})
        pages["lazy_short"] = await source.fetch_page(lazy_url, {"t1": 30, "absent": 2})
        pages["lazy_unscrolled"] = await source.fetch_page(lazy_url)
        pages["split"] = await source.fetch_page(split_url, {"wide": 3})
    return pages, nav_all, nav_tree_only


@pytest.fixture(scope="module")
def scraped(tmp_path_factory):
    """One browser session for the whole module - launching Chromium per
    test would dominate the suite's runtime."""
    root = tmp_path_factory.mktemp("pages")
    for name, html in (
        ("site", _SITE_PAGE),
        ("forbidden", _UNRENDERED_PAGE),
        ("nav", _NAV_CSS_PAGE),
        ("lazy", _LAZY_TABLE_PAGE),
        ("split", _SPLIT_TABLE_PAGE),
    ):
        (root / f"{name}.html").write_text(html)
    urls = {
        "site": (root / "site.html").as_uri(),
        "forbidden": (root / "forbidden.html").as_uri(),
        "missing": (root / "missing.html").as_uri(),
    }
    pages, nav_all, nav_tree_only = asyncio.run(
        _scrape_all(
            urls,
            (root / "nav.html").as_uri(),
            (root / "lazy.html").as_uri(),
            (root / "split.html").as_uri(),
        )
    )
    return {"pages": pages, "nav_all": nav_all, "nav_tree_only": nav_tree_only}


def test_fetch_page_captures_only_the_content_panel(scraped):
    page = scraped["pages"]["site"]
    assert page.panel.startswith('<main class="ui-ContentPanel">')
    assert "partTitle" in page.panel
    assert "ui-Sidebar" not in page.panel


def test_fetch_page_captures_title_stylesheet_links_and_inline_styles(scraped):
    page = scraped["pages"]["site"]
    assert page.title == "Section 1 - BC Building Code"
    assert page.stylesheets == ["/_next/static/chunks/a.css"]
    assert page.inline_styles == [".mjx-c{color:red}"]


def test_fetch_page_scrolls_until_every_expected_row_has_loaded(scraped):
    page = scraped["pages"]["lazy_complete"]
    assert _tr_count(page) == 23
    assert page.incomplete == {}


def test_fetch_page_reports_tables_that_never_reach_their_expected_rows(scraped):
    page = scraped["pages"]["lazy_short"]
    assert _tr_count(page) == 23
    assert page.incomplete == {"t1": [23, 30], "absent": [0, 2]}


def test_fetch_page_counts_a_split_tables_header_and_body_rows_once(scraped):
    # header (1) + body (2); the pinned-column duplicate and the table nested
    # in a cell are not rows of the grid.
    assert scraped["pages"]["split"].incomplete == {}


def test_fetch_page_without_expected_rows_does_not_scroll(scraped):
    page = scraped["pages"]["lazy_unscrolled"]
    assert _tr_count(page) == 5
    assert page.incomplete == {}


def test_fetch_page_returns_none_when_no_reading_panel_renders(scraped):
    assert scraped["pages"]["forbidden"] is None


def test_fetch_page_returns_none_for_an_unreachable_url(scraped):
    assert scraped["pages"]["missing"] is None


def test_fetch_nav_css_keeps_matching_rules_root_vars_and_font_faces(scraped):
    css = "\n".join(rule["css"] for rule in scraped["nav_all"])
    assert ".nav-tree-link { color: rgb(45, 45, 45); }" in css
    assert "@media (min-width: 48rem) { .breadcrumbs-title { max-width: 120px; } }" in css
    assert "--theme-primary-blue: #013366" in css
    assert "@font-face" in css
    assert ".unrelated" not in css


def test_fetch_nav_css_honours_the_selector_pattern(scraped):
    css = "\n".join(rule["css"] for rule in scraped["nav_tree_only"])
    assert ".nav-tree-link" in css
    assert "breadcrumbs-title" not in css


def test_fetch_nav_css_reports_each_rules_stylesheet_href(scraped):
    # Inline <style> rules have no stylesheet href; url()s in them resolve
    # against the site root.
    assert {rule["href"] for rule in scraped["nav_all"]} == {"/"}
