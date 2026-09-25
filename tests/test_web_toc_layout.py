"""Runs the layout pass in a real headless Chromium over a local page with the
saved pages' real shell (`body > svg + main > div > main.ui-ContentPanel`),
served the way build_web_pages.py serves them."""

import asyncio

import pytest
from playwright.async_api import async_playwright

from web_toc.parsing.layout_script import LAYOUT_JS, ROOT_XPATH
from web_toc.parsing.local_page_server import serve_pages
from web_toc.parsing.page_source import PlaywrightPageSource

# The panel sits 50px down the page and is its own 200px scroll container,
# as the saved pages' reading panel is.
_PAGE = """<!DOCTYPE html><html><head><style>
body{margin:0} .ui-ContentPanel{display:block;margin-top:50px;height:200px;overflow:auto}
h1{margin:0;height:30px} td,th{height:20px}
</style></head><body><svg><symbol id="bcbc-info-icon"></symbol></svg>
<main id="main-content"><div class="MainLayout">
<main class="ui-ContentPanel"><div class="reading-view__content">
<h1 class="partTitle">Part 9 - Housing</h1>
<h4 class="articleHeading">9.38.1.1. Attribution</h4>
<div id="s1">(1) A  sentence
  with   spaces.<div id="s1.clause1">(a) a clause</div></div>
<div id="t1"><table><thead><tr><th>Provision</th><th>Statement</th></tr></thead>
<tbody><tr><td colspan="2">9.3.1.1. General</td></tr><tr><td>(1)</td><td>F20 - OS2.1</td></tr>
</tbody></table></div>
<img src="/web-assets/graphics/a.jpg" alt="A figure" style="width:10px;height:10px">
<div style="height:600px"></div>
</div></main></div></main></body></html>"""

_NO_PANEL_PAGE = "<!DOCTYPE html><html><body><main><div><p>none</p></div></main></body></html>"


async def _measure(base_url):
    async with PlaywrightPageSource() as source:
        return {
            "page": await source.fetch_layout(f"{base_url}/page.html"),
            "no_panel": await source.fetch_layout(f"{base_url}/nopanel.html"),
        }


async def _in_browser(url):
    """Resolves every xpath back to its element, and re-measures with the
    panel scrolled - both straight from the browser."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        tab = await browser.new_page(viewport={"width": 1500, "height": 950})
        await tab.goto(url)
        unscrolled = await tab.evaluate(LAYOUT_JS)
        await tab.evaluate("document.querySelector('.ui-ContentPanel').scrollTop = 150")
        scrolled = await tab.evaluate(LAYOUT_JS)
        resolved = await tab.evaluate(
            """(xpaths) => xpaths.map((xp) => {
              const node = document.evaluate(xp, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
              return node ? (node.id || node.localName) : null;
            })""",
            [
                unscrolled["elements"]["s1"]["xpath"],
                unscrolled["tables"]["t1"][2]["cells"][1]["xpath"],
                unscrolled["tables"]["t1"][1]["xpath"],
                unscrolled["images"][0]["xpath"],
                ROOT_XPATH,
            ],
        )
        await browser.close()
    return unscrolled, scrolled, resolved


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    pages_dir = tmp_path_factory.mktemp("web_pages")
    (pages_dir / "page.html").write_text(_PAGE)
    (pages_dir / "nopanel.html").write_text(_NO_PANEL_PAGE)
    (pages_dir / "assets" / "graphics").mkdir(parents=True)
    (pages_dir / "assets" / "graphics" / "a.jpg").write_bytes(b"")
    with serve_pages(pages_dir) as base_url:
        layouts = asyncio.run(_measure(base_url))
        unscrolled, scrolled, resolved = asyncio.run(_in_browser(f"{base_url}/page.html"))
    return {**layouts, "unscrolled": unscrolled, "scrolled": scrolled, "resolved": resolved}


def test_root_xpath_is_the_saved_pages_content_panel():
    assert ROOT_XPATH == "/html/body/main/div/main"


def test_every_xpath_starts_at_the_content_panel(measured):
    layout = measured["page"]
    xpaths = [entry["xpath"] for entry in layout["elements"].values()]
    xpaths += [row["xpath"] for row in layout["tables"]["t1"]]
    xpaths += [cell["xpath"] for row in layout["tables"]["t1"] for cell in row["cells"]]
    xpaths += [entry["xpath"] for entry in layout["images"] + layout["headings"]]
    assert xpaths
    assert all(xp.startswith(f"{ROOT_XPATH}/") for xp in xpaths)


def test_xpaths_resolve_back_to_the_same_elements(measured):
    assert measured["resolved"] == ["s1", "td", "tr", "img", "main"]


def test_elements_are_keyed_by_id_with_collapsed_rendered_text(measured):
    elements = measured["page"]["elements"]
    assert elements["s1"]["text"] == "(1) A sentence with spaces. (a) a clause"
    assert elements["s1.clause1"]["text"] == "(a) a clause"
    assert "bcbc-info-icon" not in elements  # outside the panel


def test_tables_keep_every_row_and_cell_in_document_order(measured):
    rows = measured["page"]["tables"]["t1"]
    assert [len(row["cells"]) for row in rows] == [2, 1, 2]
    assert [cell["text"] for cell in rows[2]["cells"]] == ["(1)", "F20 - OS2.1"]
    assert rows[1]["text"] == "9.3.1.1. General"


def test_images_and_headings_are_listed(measured):
    layout = measured["page"]
    assert [(img["src"], img["text"]) for img in layout["images"]] == [
        ("/web-assets/graphics/a.jpg", "A figure")
    ]
    assert [h["text"] for h in layout["headings"]] == [
        "Part 9 - Housing",
        "9.38.1.1. Attribution",
    ]


def test_bbox_is_relative_to_the_panel_not_the_page(measured):
    h1 = measured["page"]["headings"][0]["bbox"]
    assert h1["y0"] == pytest.approx(0, abs=0.5)  # the panel is 50px down the page
    assert h1["y1"] == pytest.approx(30, abs=0.5)
    assert h1["x0"] == pytest.approx(0, abs=0.5)


def test_bbox_does_not_depend_on_how_far_the_panel_is_scrolled(measured):
    before = measured["unscrolled"]["tables"]["t1"][2]["cells"][1]["bbox"]
    after = measured["scrolled"]["tables"]["t1"][2]["cells"][1]["bbox"]
    assert after == pytest.approx(before)
    assert before["y1"] > before["y0"] and before["x1"] > before["x0"]


def test_a_page_without_the_content_panel_has_no_layout(measured):
    assert measured["no_panel"] is None
