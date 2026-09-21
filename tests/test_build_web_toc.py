import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from build_web_toc import CONTENT_FETCH_CONCURRENCY, run
from web_toc.domain.models import WebNode


def _run(coro):
    return asyncio.run(coro)


def _mock_source(mock_source_cls):
    mock_source = AsyncMock()
    mock_source_cls.return_value = mock_source
    mock_source.__aenter__.return_value = mock_source
    return mock_source


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_wires_pipeline_and_writes_images_from_every_content_bearing_node(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_download_images,
    mock_write_json,
    tmp_path,
):
    leaf = WebNode(
        type="section",
        identifier="1.1",
        citation="nbc.divA.part1.sect1",
        title="",
        path="",
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = _mock_source(mock_source_cls)
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.sect1"}
    # root has no content URL, the leaf section does
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/section-1.json" if node is leaf else None
    )
    mock_source.fetch_content.return_value = {"id": "nbc.divA.part1.sect1"}
    mock_extract_images.return_value = ["WEB_IMAGE"]

    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))

    assert leaf.unified_number == "1"
    mock_source_cls.assert_called_once_with("https://dev.buildingcode.gov.bc.ca", "2024")
    mock_build_tree.assert_called_once_with({"tree": []})
    mock_collect_citations.assert_called_once_with(root)
    mock_source.fetch_content.assert_called_once_with(
        "/data/2024/content/nbc-diva/part-1/section-1.json"
    )
    mock_extract_images.assert_called_once_with(
        {"id": "nbc.divA.part1.sect1"}, {"root", "nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1"
    )
    expected_path = str(Path(tmp_path) / "web_toc.json")
    mock_download_images.assert_called_once_with(
        ["WEB_IMAGE"], mock_source, str(Path(tmp_path) / "web_images")
    )
    mock_write_json.assert_called_once_with(root, ["WEB_IMAGE"], expected_path)


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_skips_nodes_where_content_url_returns_none(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_download_images,
    mock_write_json,
    tmp_path,
):
    leaf = WebNode(type="index", identifier="", citation="nbc.2020.vol2.index", title="", path="")
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = _mock_source(mock_source_cls)
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.2020.vol2.index"}
    mock_content_url.return_value = None  # index/conversions: no URL at all

    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))

    mock_source.fetch_content.assert_not_called()
    mock_extract_images.assert_not_called()
    mock_download_images.assert_called_once_with(
        [], mock_source, str(Path(tmp_path) / "web_images")
    )
    mock_write_json.assert_called_once_with(root, [], str(Path(tmp_path) / "web_toc.json"))


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_skips_nodes_where_fetch_content_returns_none(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_download_images,
    mock_write_json,
    tmp_path,
):
    leaf = WebNode(
        type="section", identifier="1.1", citation="nbc.divA.part1.sect1", title="", path=""
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = _mock_source(mock_source_cls)
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.sect1"}
    # root has no content URL, the leaf section does
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/section-1.json" if node is leaf else None
    )
    mock_source.fetch_content.return_value = None  # content URL exists but fetch failed/empty

    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))

    mock_source.fetch_content.assert_called_once_with(
        "/data/2024/content/nbc-diva/part-1/section-1.json"
    )
    mock_extract_images.assert_not_called()
    mock_download_images.assert_called_once_with(
        [], mock_source, str(Path(tmp_path) / "web_images")
    )
    mock_write_json.assert_called_once_with(root, [], str(Path(tmp_path) / "web_toc.json"))


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_fetches_content_bearing_nodes_concurrently(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_download_images,
    mock_write_json,
    tmp_path,
):
    leaves = [
        WebNode(
            type="section",
            identifier=str(n),
            citation=f"nbc.divA.part1.sect{n}",
            title="",
            path="",
        )
        for n in range(6)
    ]
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=leaves)
    mock_source = _mock_source(mock_source_cls)
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", *(leaf.citation for leaf in leaves)}
    mock_content_url.side_effect = lambda node, version: (
        f"/data/2024/content/{node.citation}.json" if node in leaves else None
    )

    async def _slow_fetch(url):
        await asyncio.sleep(0.2)
        return {"id": url}

    mock_source.fetch_content.side_effect = _slow_fetch
    mock_extract_images.return_value = []

    start = time.monotonic()
    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))
    elapsed = time.monotonic() - start

    assert elapsed < 0.2 * len(leaves), (
        f"expected concurrent content fetches to run faster than serial "
        f"({0.2 * len(leaves)}s), took {elapsed}s"
    )
    assert mock_source.fetch_content.call_count == len(leaves)


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_closes_the_source_even_when_a_fetch_raises(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_download_images,
    mock_write_json,
    tmp_path,
):
    leaf = WebNode(
        type="section", identifier="1.1", citation="nbc.divA.part1.sect1", title="", path=""
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = _mock_source(mock_source_cls)
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.sect1"}
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/section-1.json" if node is leaf else None
    )
    mock_source.fetch_content.side_effect = RuntimeError("boom")

    try:
        _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))
    except RuntimeError:
        pass

    mock_source.__aexit__.assert_awaited_once()


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_logs_fetch_progress_only_as_the_semaphore_admits_each_request(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_download_images,
    mock_write_json,
    tmp_path,
    capsys,
):
    leaves = [
        WebNode(
            type="section",
            identifier=str(n),
            citation=f"nbc.divA.part1.sect{n}",
            title="",
            path="",
        )
        for n in range(CONTENT_FETCH_CONCURRENCY + 2)
    ]
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=leaves)
    mock_source = _mock_source(mock_source_cls)
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", *(leaf.citation for leaf in leaves)}
    mock_content_url.side_effect = lambda node, version: (
        f"/data/2024/content/{node.citation}.json" if node in leaves else None
    )

    gate = asyncio.Event()

    async def _blocked_fetch(url):
        await gate.wait()
        return {"id": url}

    mock_source.fetch_content.side_effect = _blocked_fetch
    mock_extract_images.return_value = []

    async def scenario():
        task = asyncio.create_task(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))
        for _ in range(20):
            await asyncio.sleep(0)
        blocked_output = capsys.readouterr().err
        gate.set()
        await task
        return blocked_output

    blocked_output = _run(scenario())

    fetch_lines_while_blocked = blocked_output.count("Fetching ")
    assert fetch_lines_while_blocked == CONTENT_FETCH_CONCURRENCY, (
        f"expected exactly {CONTENT_FETCH_CONCURRENCY} in-flight fetches to be logged while the "
        f"remaining requests wait on the semaphore, but saw {fetch_lines_while_blocked}"
    )
