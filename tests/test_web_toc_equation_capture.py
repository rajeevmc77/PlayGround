"""Captures each MathJax-rendered equation on a locally served page as a PNG
and rewrites the page to show that image instead - in a real headless
Chromium, over a page with the saved pages' real shell. The fixture's
`mjx-*` elements stand in for MathJax's CHTML output: a full-width
`mjx-container` around a tight `mjx-math` glyph box."""

import asyncio
import struct

import pytest

from web_toc.parsing.equation_script import EQUATION_ASSET_DIR
from web_toc.parsing.local_page_server import serve_pages
from web_toc.parsing.page_source import PlaywrightPageSource

_EQUATION = """<div class="equation-block equation-block--{display}"{node_id}><span
class="equation-block__mathml" role="math" aria-label="{label}"><mjx-container class="MathJax"
style="display:{container}"><mjx-math style="display:inline-block;width:{w}px;height:{h}px;
background:#000"></mjx-math><mjx-assistive-mml><math><mi>W</mi></math></mjx-assistive-mml>
</mjx-container></span></div>"""


def _equation(display, label, w, h, node_id=""):
    return _EQUATION.format(
        display=display,
        node_id=f' data-node-id="{node_id}"' if node_id else "",
        label=label,
        container="block" if display == "block" else "inline-block",
        w=w,
        h=h,
    )


# A label with the raw whitespace runs the site's aria-labels carry.
_SPACED_LABEL = "W=w ×\n   4.9"

_PAGE = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{margin:0}}</style></head><body>
<main id="main-content"><div class="MainLayout"><main class="ui-ContentPanel">
<div id="s2.clause2">b) the following formula
{_equation("block", _SPACED_LABEL, 120, 30, "es1")}</div>
<div id="p3">Example {_equation("block", "0.5 kPa", 60, 20)} and
{_equation("inline", "l_c", 20, 10)}</div>
<div id="t1"><table><tr><th>Value of {_equation("inline", "C_w", 24, 12, "eg2")}</th></tr></table>
<table class="table-block__table--pinned-col"><tr><th>Value of
{_equation("inline", "C_w", 24, 12, "eg2")}</th></tr></table></div>
</main></div></main></body></html>"""

_PLAIN_PAGE = """<!DOCTYPE html><html><body><main><div><main class="ui-ContentPanel">
<div id="s1">No formulas here.</div></main></div></main></body></html>"""


async def _capture(base_url):
    async with PlaywrightPageSource(device_scale_factor=2) as source:
        return {
            "page": await source.capture_equations(f"{base_url}/page.html"),
            "plain": await source.capture_equations(f"{base_url}/plain.html"),
        }


async def _render(base_url):
    """The rewritten page, served back with its PNGs, as a browser sees it."""
    async with PlaywrightPageSource() as source:
        tab = await source._context.new_page()
        await tab.goto(f"{base_url}/rewritten.html", wait_until="load")
        seen = await tab.evaluate(
            """() => [...document.querySelectorAll('img.equation-image')].map((img) => ({
              key: img.dataset.equation, owner: img.dataset.owner, alt: img.alt,
              loaded: img.complete && img.naturalWidth > 0,
              width: img.getBoundingClientRect().width,
              height: img.getBoundingClientRect().height,
            }))"""
        )
        mathjax_left = await tab.evaluate("document.querySelectorAll('mjx-container').length")
        await tab.close()
    return seen, mathjax_left


def _png_size(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])  # the IHDR chunk's width, height


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    pages_dir = tmp_path_factory.mktemp("web_pages")
    (pages_dir / "page.html").write_text(_PAGE)
    (pages_dir / "plain.html").write_text(_PLAIN_PAGE)
    with serve_pages(pages_dir) as base_url:
        result = asyncio.run(_capture(base_url))
        page = result["page"]
        (pages_dir / "rewritten.html").write_text(page.html)
        images_dir = pages_dir / "assets" / EQUATION_ASSET_DIR
        images_dir.mkdir(parents=True)
        for key, data in page.images.items():
            (images_dir / f"{key}.png").write_bytes(data)
        result["rendered"], result["mathjax_left"] = asyncio.run(_render(base_url))
    return result


def test_every_equation_gets_one_png_keyed_by_its_owner_and_node_id(captured):
    # The site reuses a node id for the same formula in several places, so
    # the owner's id makes the key unique; one with no node id is "eq", and
    # a repeat within one owner is "-n". The pinned-column copy of a header
    # cell is the same equation.
    assert sorted(captured["page"].images) == ["p3.eq", "p3.eq-2", "s2.clause2.es1", "t1.eg2"]
    assert all(data.startswith(b"\x89PNG") for data in captured["page"].images.values())


def test_each_png_is_the_tight_glyph_box_at_the_capture_scale(captured):
    images = captured["page"].images
    assert _png_size(images["s2.clause2.es1"]) == (240, 60)
    assert _png_size(images["p3.eq-2"]) == (40, 20)


def test_the_rewritten_page_shows_each_png_in_place_of_mathjax(captured):
    seen, mathjax_left = captured["rendered"], captured["mathjax_left"]
    assert mathjax_left == 0
    assert all(img["loaded"] for img in seen)
    by_key = {img["key"]: img for img in seen}
    formula = by_key["s2.clause2.es1"]
    assert formula["owner"] == "s2.clause2"
    assert formula["alt"] == "W=w × 4.9"  # whitespace runs collapsed
    assert (formula["width"], formula["height"]) == (120, 30)
    assert by_key["p3.eq-2"]["owner"] == "p3"
    assert by_key["t1.eg2"]["owner"] == "t1"
    assert len(seen) == 5  # both copies of the pinned header cell


def test_the_rewritten_page_keeps_its_doctype_and_panel(captured):
    html = captured["page"].html
    assert html.startswith("<!DOCTYPE html>")
    assert 'class="ui-ContentPanel"' in html
    assert f'src="/web-assets/{EQUATION_ASSET_DIR}/s2.clause2.es1.png"' in html


def test_a_page_without_equations_is_left_alone(captured):
    assert captured["plain"] is None
