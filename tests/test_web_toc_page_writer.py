import asyncio

import pytest

from web_toc.output.page_writer import (
    DOWNLOAD_CONCURRENCY,
    asset_file,
    download_assets,
    page_file,
    write_page,
)


class _FakeSource:
    def __init__(self, payloads, delay=0.0):
        self.payloads = payloads
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.requested = []

    async def fetch_bytes(self, path):
        self.requested.append(path)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        return self.payloads.get(path)


def test_asset_file_mirrors_the_site_path_under_the_assets_dir(tmp_path):
    assert asset_file(tmp_path, "/_next/static/media/f.woff2") == (
        tmp_path / "_next" / "static" / "media" / "f.woff2"
    )


@pytest.mark.parametrize("path", ["/../secret.txt", "/a/../../b", "relative.css", "/"])
def test_asset_file_rejects_paths_outside_the_assets_dir(tmp_path, path):
    assert asset_file(tmp_path, path) is None


def test_page_file_names_the_file_after_the_citation(tmp_path):
    assert page_file(tmp_path, "nbc.divA.part1.sect1") == tmp_path / "nbc.divA.part1.sect1.html"


@pytest.mark.parametrize("citation", ["../x", "a/b", "", "a b"])
def test_page_file_rejects_unsafe_citations(tmp_path, citation):
    assert page_file(tmp_path, citation) is None


def test_write_page_creates_the_directory_and_writes_utf8(tmp_path):
    pages_dir = tmp_path / "web_pages"
    write_page(pages_dir, "nbc.divA.part1.sect1", "<p>Clause é</p>")
    assert (pages_dir / "nbc.divA.part1.sect1.html").read_text(encoding="utf-8") == (
        "<p>Clause é</p>"
    )


def test_write_page_raises_for_an_unsafe_citation(tmp_path):
    with pytest.raises(ValueError):
        write_page(tmp_path, "../escape", "x")


def test_download_assets_writes_each_file_at_its_mirrored_path(tmp_path):
    source = _FakeSource({"/a/x.css": b"css", "/g/y.jpg": b"jpg"})
    failed = asyncio.run(download_assets(["/a/x.css", "/g/y.jpg"], source, tmp_path))
    assert failed == []
    assert (tmp_path / "a" / "x.css").read_bytes() == b"css"
    assert (tmp_path / "g" / "y.jpg").read_bytes() == b"jpg"


def test_download_assets_reports_failed_and_unsafe_paths_without_writing(tmp_path):
    source = _FakeSource({})
    failed = asyncio.run(download_assets(["/missing.jpg", "/../evil"], source, tmp_path))
    assert failed == ["/missing.jpg", "/../evil"]
    assert source.requested == ["/missing.jpg"]
    assert list(tmp_path.iterdir()) == []


def test_download_assets_fetches_concurrently_but_bounded(tmp_path):
    paths = [f"/g/{i}.jpg" for i in range(DOWNLOAD_CONCURRENCY * 3)]
    source = _FakeSource({p: b"x" for p in paths}, delay=0.01)
    asyncio.run(download_assets(paths, source, tmp_path))
    assert source.max_in_flight == DOWNLOAD_CONCURRENCY


def test_download_assets_with_no_paths_does_nothing(tmp_path):
    assert asyncio.run(download_assets([], _FakeSource({}), tmp_path)) == []
