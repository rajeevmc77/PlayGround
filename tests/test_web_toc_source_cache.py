import asyncio
import json

import pytest

from web_toc.domain.models import WebNode
from web_toc.output.source_cache import (
    CONTENT_FETCH_CONCURRENCY,
    cache_contents,
    write_navigation,
    write_snapshot,
)
from web_toc.parsing.local_source import LocalWebSource

SECTION_URL = "/data/2024/content/nbc-diva/part-1/section-1.json"
SECTION2_URL = "/data/2024/content/nbc-diva/part-1/section-2.json"


def _section(n):
    return WebNode(
        type="section",
        identifier=f"1.{n}",
        citation=f"nbc.divA.part1.sect{n}",
        title="",
        path=f"/code/nbc.divA/1/{n}",
    )


def _root(*children):
    part = WebNode(
        type="part",
        identifier="1",
        citation="nbc.divA.part1",
        title="",
        path="/code/nbc.divA/1",
        children=list(children),
    )
    return WebNode(type="root", identifier="", citation="root", title="", path="/", children=[part])


class _FakeHttp:
    def __init__(self, contents, delay=0.0):
        self.contents = contents
        self.delay = delay
        self.requested = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def fetch_content(self, path):
        self.requested.append(path)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        return self.contents.get(path)


def test_cache_contents_writes_each_content_bearing_nodes_json_by_citation(tmp_path):
    http = _FakeHttp({SECTION_URL: {"id": "nbc.divA.part1.sect1"}})

    cached = asyncio.run(cache_contents(http, _root(_section(1)), "2024", tmp_path))

    assert cached == {"nbc.divA.part1.sect1": {"id": "nbc.divA.part1.sect1"}}
    assert http.requested == [SECTION_URL]  # the part itself has no content URL
    written = json.loads((tmp_path / "content" / "nbc.divA.part1.sect1.json").read_text())
    assert written == {"id": "nbc.divA.part1.sect1"}


def test_cache_contents_skips_and_reports_absent_content(tmp_path, capsys):
    http = _FakeHttp({SECTION_URL: {"id": "s1"}})

    cached = asyncio.run(cache_contents(http, _root(_section(1), _section(2)), "2024", tmp_path))

    assert list(cached) == ["nbc.divA.part1.sect1"]
    assert not (tmp_path / "content" / "nbc.divA.part1.sect2.json").exists()
    assert f"no content at {SECTION2_URL}" in capsys.readouterr().err


def test_cache_contents_fetches_concurrently_but_bounded(tmp_path):
    sections = [_section(n) for n in range(CONTENT_FETCH_CONCURRENCY * 3)]
    http = _FakeHttp({}, delay=0.01)

    asyncio.run(cache_contents(http, _root(*sections), "2024", tmp_path))

    assert http.max_in_flight == CONTENT_FETCH_CONCURRENCY


def test_cache_contents_refuses_a_citation_that_is_not_a_safe_file_name(tmp_path):
    section = _section(1)
    section.citation = "nbc divA.part1.sect1"  # still a section id, but has a space
    http = _FakeHttp({"/data/2024/content/nbc diva/part-1/section-1.json": {"id": "s1"}})
    with pytest.raises(ValueError, match="Unsafe citation"):
        asyncio.run(cache_contents(http, _root(section), "2024", tmp_path))


def test_write_navigation_and_local_source_round_trip(tmp_path):
    nav = {"tree": [{"id": "nbc.divA"}]}
    write_navigation(tmp_path, nav)

    assert LocalWebSource(tmp_path).fetch_navigation_tree() == nav


def test_local_source_reads_cached_content_by_citation(tmp_path):
    http = _FakeHttp({SECTION_URL: {"id": "s1"}})
    asyncio.run(cache_contents(http, _root(_section(1)), "2024", tmp_path))

    source = LocalWebSource(tmp_path)

    assert source.fetch_content("nbc.divA.part1.sect1") == {"id": "s1"}
    assert source.fetch_content("nbc.divA.part1.sect9") is None


def test_write_snapshot_and_local_source_round_trip(tmp_path):
    write_snapshot(tmp_path, "2024", "2024-03-08")

    assert LocalWebSource(tmp_path).fetch_snapshot() == {"version": "2024", "date": "2024-03-08"}


def test_local_source_without_a_snapshot_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_web_pages.py"):
        LocalWebSource(tmp_path).fetch_snapshot()


def test_local_source_refuses_an_unsafe_citation(tmp_path):
    assert LocalWebSource(tmp_path).fetch_content("../../etc/passwd") is None


def test_local_source_without_a_cached_navigation_tree_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_web_pages.py"):
        LocalWebSource(tmp_path).fetch_navigation_tree()
