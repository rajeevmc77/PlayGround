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
_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{margin:0} .ui-ContentPanel{display:block;margin-top:50px;height:200px;overflow:auto}
h1{margin:0;height:30px} td,th{height:20px}
.compound-ref{display:inline-block} .compound-ref:before{content:"[ "}
.compound-ref:after{content:" ]"} .hidden{display:none} .term{font-style:italic}
</style></head><body><svg><symbol id="bcbc-info-icon"></symbol></svg>
<main id="main-content"><div class="MainLayout">
<main class="ui-ContentPanel"><div class="reading-view__content">
<h1 class="partTitle">Part 9 - Housing</h1>
<h4 class="articleHeading">9.38.1.1. Attribution</h4>
<div id="refs"><span class="compound-ref"><span>F20</span> - <span>OS2.1</span></span><span
class="compound-ref"><span>F22</span> - <span>OS2.5</span></span><span class="hidden">x</span>
Applies.</div>
<div id="s1">(1) A  sentence
  with   spaces.<div id="s1.clause1">(a) a clause</div></div>
<div id="t1"><table><thead><tr><th>Provision</th><th>Statement</th></tr></thead>
<tbody><tr><td colspan="2">9.3.1.1. General</td></tr><tr><td>(1)</td><td>F20 - OS2.1</td></tr>
</tbody></table></div>
<div id="t2"><table class="table-block__table--split-header"><tr><th>H1</th><th>H2</th></tr></table>
<table class="table-block__table--split-header table-block__table--pinned-col"><tr><th>H1</th></tr>
</table><table class="table-block__table--split-body"><tr><td>a</td><td>b<table><tr><td>nested</td>
</tr></table></td></tr><tr><td>c</td><td>d</td></tr></table></div>
<div id="s2">b) the formula <img class="equation-image" src="/web-assets/equations/es1.png"
alt="W=w×4.9" data-equation="es1" data-owner="s2"
style="display:inline-block;width:40px;height:10px"></div>
<div id="t3"><table><tr><th>Value of <img class="equation-image" alt="C_w" data-equation="eg2"
data-owner="t3" src="/web-assets/equations/eg2.png" style="width:8px;height:8px"></th></tr>
</table><table class="table-block__table--pinned-col"><tr><th>Value of <img alt="C_w"
class="equation-image" data-equation="eg2" data-owner="t3" src="/web-assets/equations/eg2.png">
</th></tr></table></div>
<div id="em1">a new <span class="term">building</span>, <strong>Bold <em>both</em>
</strong><span class="hidden">gone</span></div>
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


def _all_entries(layout):
    rows = layout["tables"]["t1"]
    cells = [cell for row in rows for cell in row["cells"]]
    return [*layout["elements"].values(), *rows, *cells, *layout["images"], *layout["headings"]]


def test_every_xpath_starts_at_the_content_panel(measured):
    xpaths = [entry["xpath"] for entry in _all_entries(measured["page"])]
    assert xpaths
    assert all(xp.startswith(f"{ROOT_XPATH}/") for xp in xpaths)


def test_xpaths_resolve_back_to_the_same_elements(measured):
    assert measured["resolved"] == ["s1", "td", "tr", "img", "main"]


def test_elements_are_keyed_by_id_with_collapsed_rendered_text(measured):
    elements = measured["page"]["elements"]
    assert elements["s1"]["text"] == "(1) A sentence with spaces. (a) a clause"
    assert elements["s1.clause1"]["text"] == "(a) a clause"
    assert "bcbc-info-icon" not in elements  # outside the panel


def test_text_includes_css_generated_content_and_skips_hidden_elements(measured):
    # The site draws each compound reference's brackets with ::before/::after.
    text = measured["page"]["elements"]["refs"]["text"]
    assert text == "[ F20 - OS2.1 ] [ F22 - OS2.5 ] Applies."


def test_emphasis_records_the_rendered_bold_and_italic_ranges(measured):
    em1 = measured["page"]["elements"]["em1"]
    assert em1["text"] == "a new building, Bold both"
    assert em1["emphasis"] == [[6, 14, "i"], [16, 21, "b"], [21, 25, "bi"]]


def test_plain_text_has_no_emphasis_and_header_cells_render_bold(measured):
    assert measured["page"]["elements"]["s1"]["emphasis"] == []
    header = measured["page"]["tables"]["t1"][0]["cells"][0]
    assert (header["text"], header["emphasis"]) == ("Provision", [[0, 9, "b"]])


def test_tables_keep_every_row_and_cell_in_document_order(measured):
    rows = measured["page"]["tables"]["t1"]
    assert [len(row["cells"]) for row in rows] == [2, 1, 2]
    assert [cell["text"] for cell in rows[2]["cells"]] == ["(1)", "F20 - OS2.1"]
    assert rows[1]["text"] == "9.3.1.1. General"


def test_a_split_table_is_one_grid_of_its_header_and_body_tables(measured):
    # Wide tables render a header <table>, a pinned-first-column duplicate
    # of it, and a body <table>; a table nested in a cell is not a row.
    rows = measured["page"]["tables"]["t2"]
    assert [[cell["text"] for cell in row["cells"]] for row in rows] == [
        ["H1", "H2"],
        ["a", "b nested"],
        ["c", "d"],
    ]
    assert rows[0]["xpath"].endswith("div[4]/table[1]/tbody[1]/tr[1]")
    assert rows[1]["xpath"].endswith("div[4]/table[3]/tbody[1]/tr[1]")


def test_images_and_headings_are_listed(measured):
    layout = measured["page"]
    assert [(img["src"], img["text"]) for img in layout["images"]] == [
        ("/web-assets/graphics/a.jpg", "A figure")
    ]
    assert [h["text"] for h in layout["headings"]] == [
        "Part 9 - Housing",
        "9.38.1.1. Attribution",
    ]


def test_equation_images_are_listed_apart_from_figures_once_each(measured):
    # A pinned-column copy of a header cell is the same equation again.
    equations = measured["page"]["equations"]
    assert [(eq["key"], eq["owner"], eq["text"]) for eq in equations] == [
        ("es1", "s2", "W=w×4.9"),
        ("eg2", "t3", "C_w"),
    ]
    first = equations[0]
    assert first["xpath"].startswith(f"{ROOT_XPATH}/") and first["xpath"].endswith("/img[1]")
    assert first["bbox"]["x1"] - first["bbox"]["x0"] == pytest.approx(40, abs=0.5)
    assert first["bbox"]["y1"] - first["bbox"]["y0"] == pytest.approx(10, abs=0.5)


def test_an_equation_image_adds_no_text_to_what_holds_it(measured):
    assert measured["page"]["elements"]["s2"]["text"] == "b) the formula"
    assert measured["page"]["tables"]["t3"][0]["cells"][0]["text"] == "Value of"


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


# A web font still downloading when `load` fires (the saved pages' BC Sans
# often is, with many tabs measured at once) - the block the font resizes is
# stood in for by one the page resizes when `document.fonts.ready` resolves.
_LATE_FONT_PAGE = """<!DOCTYPE html><html><body><main><div>
<main class="ui-ContentPanel"><div id="late" style="height:10px"></div></main>
</div></main><script>
window.addEventListener('load', () => {
  const face = new FontFace('Late', 'url(/late.woff2)');
  document.fonts.add(face);
  face.load().catch(() => null);
  document.fonts.ready.then(() => { document.getElementById('late').style.height = '100px'; });
});
</script></body></html>"""


async def _measure_with_a_late_font(url):
    async def late_font(route):
        await asyncio.sleep(0.5)
        await route.fulfill(status=404)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        tab = await browser.new_page()
        await tab.route("**/late.woff2", late_font)
        await tab.goto(url, wait_until="load")
        layout = await tab.evaluate(LAYOUT_JS)
        await browser.close()
    return layout


def test_the_layout_is_measured_once_the_pages_web_fonts_have_loaded(tmp_path):
    (tmp_path / "late.html").write_text(_LATE_FONT_PAGE)
    with serve_pages(tmp_path) as base_url:
        layout = asyncio.run(_measure_with_a_late_font(f"{base_url}/late.html"))
    bbox = layout["elements"]["late"]["bbox"]
    assert bbox["y1"] - bbox["y0"] == 100
