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


def _page(body, title="Section 1 - BC Building Code", inline_styles=None, incomplete=None):
    return ScrapedPage(
        panel=f'<main class="ui-ContentPanel">{body}</main>',
        title=title,
        stylesheets=[CSS],
        inline_styles=inline_styles or [],
        incomplete=incomplete or {},
    )


class _FakeBrowser:
    """`pages[url]` is one ScrapedPage (or None), or a list served one per
    successive fetch of that url (to exercise the retry)."""

    def __init__(self, pages, delay=0.0, layout=None):
        self.pages = pages
        self.delay = delay
        self.layout = layout if layout is not None else {"elements": {}}
        self.in_flight = 0
        self.max_in_flight = 0
        self.nav_css_calls = []
        self.expected_rows = {}
        self.fetch_counts = {}
        self.layout_urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def fetch_page(self, url, expected_rows=None):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        self.expected_rows[url] = expected_rows
        attempt = self.fetch_counts.get(url, 0)
        self.fetch_counts[url] = attempt + 1
        page = self.pages.get(url)
        return page[min(attempt, len(page) - 1)] if isinstance(page, list) else page

    async def fetch_layout(self, url):
        self.layout_urls.append(url)
        return self.layout

    async def fetch_nav_css(self, url, pattern):
        self.nav_css_calls.append((url, pattern))
        return [
            {"href": CSS, "css": "@font-face { src: url(../media/f.woff2); }"},
            {"href": "/", "css": ".nav-tree-link { color: red; }"},
        ]


SECTION_CONTENT_URL = "/data/2024/content/nbc-diva/part-1/section-1.json"
_SECTION_CONTENT = {
    "id": "nbc.divA.part1.sect1",
    "content": [
        {
            "type": "table",
            "id": "nbc.divA.part1.sect1.table1",
            "structure": {"header_rows": [{}], "body_rows": [{}, {}]},
        },
        {"type": "figure", "id": "nbc.divA.part1.sect1.figure1", "graphic": {"src": "g/f1"}},
    ],
}


class _FakeHttp:
    def __init__(self, nav=_NAV, assets=None, contents=None):
        self.nav = nav
        self.assets = assets if assets is not None else {}
        self.contents = contents if contents is not None else {}
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def fetch_navigation_tree(self):
        return self.nav

    async def fetch_content(self, path):
        return self.contents.get(path)

    async def fetch_image(self, src):
        return self.assets.get(f"/{src}.jpg")

    async def fetch_bytes(self, path):
        self.requested.append(path)
        return self.assets.get(path)


def _run(tmp_path, browser, http, only=None):
    """Returns run()'s report of pages left incomplete."""
    with (
        patch("build_web_pages.PlaywrightPageSource", return_value=browser),
        patch("build_web_pages.HttpxWebSource", return_value=http),
    ):
        return asyncio.run(run(BASE, "2024", "2024-03-08", str(tmp_path), only))


def _build(tmp_path, browser, http, only=None):
    _run(tmp_path, browser, http, only)
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


def _content_http(**kwargs):
    return _FakeHttp(contents={SECTION_CONTENT_URL: _SECTION_CONTENT}, **kwargs)


def test_run_caches_the_navigation_tree_and_every_content_json(tmp_path):
    _build(tmp_path, _FakeBrowser(_default_pages()), _content_http())
    source = tmp_path / "web_source"
    assert json.loads((source / "navigation.json").read_text()) == _NAV
    cached = json.loads((source / "content" / "nbc.divA.part1.sect1.json").read_text())
    assert cached == _SECTION_CONTENT


def test_run_asks_the_browser_for_every_row_the_content_json_says_a_table_has(tmp_path):
    browser = _FakeBrowser(_default_pages())
    _build(tmp_path, browser, _content_http())
    assert browser.expected_rows[SECTION_URL] == {"nbc.divA.part1.sect1.table1": 3}
    assert browser.expected_rows[PART_URL] == {}  # a part page has no content JSON


def test_run_retries_an_incomplete_page_once_and_keeps_the_complete_retry(tmp_path):
    pages = _default_pages()
    short = _page("short", incomplete={"nbc.divA.part1.sect1.table1": [1, 3]})
    pages[SECTION_URL] = [short, _page("complete")]
    browser = _FakeBrowser(pages)

    incomplete = _run(tmp_path, browser, _content_http())

    assert browser.fetch_counts[SECTION_URL] == 2
    assert incomplete == {}
    section = (tmp_path / "web_pages" / "nbc.divA.part1.sect1.html").read_text()
    assert "complete" in section


def test_run_saves_but_reports_a_page_still_incomplete_after_the_retry(tmp_path, capsys):
    pages = _default_pages()
    short = _page("short", incomplete={"nbc.divA.part1.sect1.table1": [1, 3]})
    pages[SECTION_URL] = [short, short]

    incomplete = _run(tmp_path, _FakeBrowser(pages), _content_http())

    assert incomplete == {"nbc.divA.part1.sect1": {"nbc.divA.part1.sect1.table1": [1, 3]}}
    assert (tmp_path / "web_pages" / "nbc.divA.part1.sect1.html").exists()


def test_run_writes_a_layout_file_per_saved_page_measured_from_the_local_copy(tmp_path):
    layout = {"elements": {"x": {"xpath": "/html/body/main/div/main/div[1]"}}}
    browser = _FakeBrowser(_default_pages(), layout=layout)

    out = _build(tmp_path, browser, _content_http())

    for citation in ("nbc.divA.part1", "nbc.divA.part1.sect1"):
        written = json.loads((out / f"{citation}.layout.json").read_text())
        assert written == layout
    assert sorted(url.rsplit("/", 1)[-1] for url in browser.layout_urls) == [
        "nbc.divA.part1.html",
        "nbc.divA.part1.sect1.html",
    ]
    assert all(url.startswith("http://127.0.0.1:") for url in browser.layout_urls)


def test_run_reports_a_saved_page_with_no_content_panel(tmp_path, capsys):
    browser = _FakeBrowser(_default_pages())
    browser.layout = None  # the page has no content panel

    out = _build(tmp_path, browser, _content_http())

    assert not (out / "nbc.divA.part1.sect1.layout.json").exists()
    assert "no layout for nbc.divA.part1.sect1" in capsys.readouterr().err


def test_run_downloads_every_figure_in_the_cached_content(tmp_path):
    http = _content_http(assets={"/g/f1.jpg": b"figure"})
    _build(tmp_path, _FakeBrowser(_default_pages()), http)
    image = tmp_path / "web_images" / "nbc.divA.part1.sect1.figure1.jpg"
    assert image.read_bytes() == b"figure"


def test_run_with_only_scrapes_just_that_page_and_keeps_the_rest_of_the_manifest(tmp_path):
    pages_dir = tmp_path / "web_pages"
    pages_dir.mkdir()
    (pages_dir / "pages.json").write_text(json.dumps({"nbc.divA.part1": "Part 1 (old)"}))
    browser = _FakeBrowser(_default_pages())

    _build(tmp_path, browser, _content_http(), only="nbc.divA.part1.sect1")

    assert list(browser.fetch_counts) == [SECTION_URL]
    manifest = json.loads((pages_dir / "pages.json").read_text())
    assert manifest == {
        "nbc.divA.part1": "Part 1 (old)",
        "nbc.divA.part1.sect1": "Section 1 - BC Building Code",
    }
