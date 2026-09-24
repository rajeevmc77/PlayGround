import asyncio
import json
from unittest.mock import patch

from build_web_pages import PAGE_FETCH_CONCURRENCY, run
from web_toc.domain.models import ScrapedPage

BASE = "https://site.example"
PART_URL = f"{BASE}/code/nbc.divA/1?version=2024&date=2024-03-08"
SECTION_URL = f"{BASE}/code/nbc.divA/1/1?version=2024&date=2024-03-08"
CSS = "/_next/static/chunks/a.css"

_NAV = {
    "tree": [
        {
            "id": "nbc.divA",
            "type": "division",
            "title": "Division A - Compliance",
            "path": "/code/nbc.divA",
            "children": [
                {
                    "id": "nbc.divA.part1",
                    "type": "part",
                    "number": "1",
                    "title": "Part 1 - Compliance",
                    "path": "/code/nbc.divA/1",
                    "children": [
                        {
                            "id": "nbc.divA.part1.sect1",
                            "type": "section",
                            "number": "1.1",
                            "title": "1.1 General",
                            "path": "/code/nbc.divA/1/1",
                        }
                    ],
                }
            ],
        }
    ]
}


def _page(body, title="Section 1 - BC Building Code", inline_styles=None):
    return ScrapedPage(
        panel=f'<main class="ui-ContentPanel">{body}</main>',
        title=title,
        stylesheets=[CSS],
        inline_styles=inline_styles or [],
    )


class _FakeBrowser:
    def __init__(self, pages, delay=0.0):
        self.pages = pages
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.nav_css_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def fetch_page(self, url):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        return self.pages.get(url)

    async def fetch_nav_css(self, url, pattern):
        self.nav_css_calls.append((url, pattern))
        return [
            {"href": CSS, "css": "@font-face { src: url(../media/f.woff2); }"},
            {"href": "/", "css": ".nav-tree-link { color: red; }"},
        ]


class _FakeHttp:
    def __init__(self, nav=_NAV, assets=None):
        self.nav = nav
        self.assets = assets if assets is not None else {}
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def fetch_navigation_tree(self):
        return self.nav

    async def fetch_bytes(self, path):
        self.requested.append(path)
        return self.assets.get(path)


def _build(tmp_path, browser, http):
    with (
        patch("build_web_pages.PlaywrightPageSource", return_value=browser),
        patch("build_web_pages.HttpxWebSource", return_value=http),
    ):
        asyncio.run(run(BASE, "2024", "2024-03-08", str(tmp_path)))
    return tmp_path / "web_pages"


def _default_pages():
    return {
        PART_URL: _page('<div class="partRenderer">P</div>', title="Part 1 - BC Building Code"),
        SECTION_URL: _page('<img src="/graphics/eg/1.jpg"><div class="sectionRenderer">S</div>'),
    }


def test_run_writes_one_composed_page_per_scraped_target(tmp_path):
    out = _build(tmp_path, _FakeBrowser(_default_pages()), _FakeHttp())
    section = (out / "nbc.divA.part1.sect1.html").read_text()
    assert '<link rel="stylesheet" href="/web-assets/_next/static/chunks/a.css">' in section
    assert 'src="/web-assets/graphics/eg/1.jpg"' in section
    assert '<div class="sectionRenderer">S</div>' in section
    assert (out / "nbc.divA.part1.html").exists()


def test_run_never_scrapes_the_division(tmp_path):
    browser = _FakeBrowser(_default_pages())
    out = _build(tmp_path, browser, _FakeHttp())
    assert not (out / "nbc.divA.html").exists()


def test_run_writes_a_manifest_of_scraped_pages_and_omits_failures(tmp_path):
    pages = _default_pages()
    pages[PART_URL] = None
    out = _build(tmp_path, _FakeBrowser(pages), _FakeHttp())
    manifest = json.loads((out / "pages.json").read_text())
    assert manifest == {"nbc.divA.part1.sect1": "Section 1 - BC Building Code"}
    assert not (out / "nbc.divA.part1.html").exists()


def test_run_mirrors_stylesheets_images_and_the_fonts_those_stylesheets_use(tmp_path):
    http = _FakeHttp(
        assets={
            CSS: b"@font-face{src:url(../media/f.woff2)}",
            "/graphics/eg/1.jpg": b"jpg",
            "/_next/static/media/f.woff2": b"font",
        }
    )
    out = _build(tmp_path, _FakeBrowser(_default_pages()), http)
    assets = out / "assets"
    assert (assets / "_next/static/chunks/a.css").read_bytes().startswith(b"@font-face")
    assert (assets / "graphics/eg/1.jpg").read_bytes() == b"jpg"
    assert (assets / "_next/static/media/f.woff2").read_bytes() == b"font"


def test_run_reports_each_failed_asset_once(tmp_path, capsys):
    _build(tmp_path, _FakeBrowser(_default_pages()), _FakeHttp(assets={}))
    err = capsys.readouterr().err
    assert err.count("skipped asset /graphics/eg/1.jpg") == 1


def test_run_mirrors_assets_referenced_by_inline_styles(tmp_path):
    pages = _default_pages()
    pages[SECTION_URL] = _page("S", inline_styles=["@font-face{src:url(/fonts/mjx.woff)}"])
    http = _FakeHttp(assets={"/fonts/mjx.woff": b"mjx"})
    out = _build(tmp_path, _FakeBrowser(pages), http)
    assert (out / "assets/fonts/mjx.woff").read_bytes() == b"mjx"


def test_run_writes_the_rebased_site_nav_stylesheet(tmp_path):
    browser = _FakeBrowser(_default_pages())
    out = _build(tmp_path, browser, _FakeHttp())
    css = (out / "assets" / "site-nav.css").read_text()
    assert 'url("/web-assets/_next/static/media/f.woff2")' in css
    assert ".nav-tree-link { color: red; }" in css
    assert browser.nav_css_calls == [(PART_URL, "nav-tree|breadcrumbs")]


def test_run_scrapes_pages_concurrently_but_bounded(tmp_path):
    children = [
        {
            "id": f"nbc.divA.part1.sect{i}",
            "type": "section",
            "number": f"1.{i}",
            "title": f"1.{i} S",
            "path": f"/code/nbc.divA/1/{i}",
        }
        for i in range(PAGE_FETCH_CONCURRENCY * 3)
    ]
    nav = {"tree": [{**_NAV["tree"][0]["children"][0], "children": children}]}
    browser = _FakeBrowser({}, delay=0.01)
    _build(tmp_path, browser, _FakeHttp(nav=nav))
    assert browser.max_in_flight == PAGE_FETCH_CONCURRENCY
