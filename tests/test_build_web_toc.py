import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from build_web_toc import CONTENT_FETCH_CONCURRENCY, _attach_notes, run
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
@patch("build_web_toc.number_images")
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
    mock_number_images,
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

    assert leaf.unified_number == "1.1"
    mock_source_cls.assert_called_once_with("https://dev.buildingcode.gov.bc.ca", "2024")
    mock_build_tree.assert_called_once_with({"tree": []})
    mock_collect_citations.assert_called_once_with(root)
    mock_source.fetch_content.assert_called_once_with(
        "/data/2024/content/nbc-diva/part-1/section-1.json"
    )
    mock_extract_images.assert_called_once_with(
        {"id": "nbc.divA.part1.sect1"}, {"root", "nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1"
    )
    mock_number_images.assert_called_once()
    assert mock_number_images.call_args.args[0] == ["WEB_IMAGE"]
    assert isinstance(mock_number_images.call_args.args[1], dict)
    expected_path = str(Path(tmp_path) / "bcbc_web.json")
    mock_download_images.assert_called_once_with(
        ["WEB_IMAGE"], mock_source, str(Path(tmp_path) / "web_images")
    )
    mock_write_json.assert_called_once_with(root, ["WEB_IMAGE"], expected_path)


@patch("build_web_toc.assign_unified_numbers")
@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_tables")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_attaches_notes_before_resolving_their_tables_and_images(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_extract_tables,
    mock_download_images,
    mock_write_json,
    mock_assign_unified_numbers,
    tmp_path,
):
    leaf = WebNode(
        type="part_appendix",
        identifier="",
        citation="nbc.divA.part1.appendix",
        title="",
        path="",
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = _mock_source(mock_source_cls)
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.appendix"}
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/appendix.json" if node is leaf else None
    )
    mock_source.fetch_content.return_value = {
        "id": "nbc.divA.part1.appendix",
        "application_notes": [
            {
                "id": "nbc.divA.part1.appendix.appnote2",
                "type": "application_note",
                "number": "1.1.1.1.(3)",
                "title": "T",
            }
        ],
    }
    mock_extract_images.return_value = []
    mock_extract_tables.return_value = []

    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))

    notes = [child for child in leaf.children if child.type == "Note"]
    assert len(notes) == 1
    assert notes[0].identifier == "A-1.1.1.1.(3)"

    tables_citations = mock_extract_tables.call_args.args[1]
    images_citations = mock_extract_images.call_args.args[1]
    assert "nbc.divA.part1.appendix.appnote2" in tables_citations
    assert "nbc.divA.part1.appendix.appnote2" in images_citations


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_tables")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_attaches_and_numbers_tables_from_every_content_bearing_node(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_extract_tables,
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
    table_node = WebNode(
        type="Table",
        identifier="table1",
        citation="nbc.divA.part1.sect1.table1",
        title="Diameter of Nails",
        path="",
    )
    mock_source = _mock_source(mock_source_cls)
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.sect1"}
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/section-1.json" if node is leaf else None
    )
    mock_source.fetch_content.return_value = {"id": "nbc.divA.part1.sect1"}
    mock_extract_images.return_value = []
    mock_extract_tables.return_value = [("nbc.divA.part1.sect1", table_node)]

    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))

    mock_extract_tables.assert_called_once_with(
        {"id": "nbc.divA.part1.sect1"}, {"root", "nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1"
    )
    assert leaf.children == [table_node]
    assert table_node.unified_number == "1.1.Tbl1"


@patch("build_web_toc.write_json")
@patch("build_web_toc.download_images")
@patch("build_web_toc.extract_body")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_attaches_and_numbers_body_text_from_every_content_bearing_node(
    mock_source_cls,
    mock_build_tree,
    mock_collect_citations,
    mock_content_url,
    mock_extract_images,
    mock_extract_body,
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
    clause_node = WebNode(
        type="Clause",
        identifier="(a)",
        citation="nbc.divA.part1.sect1.sent1.clause1",
        title="",
        path="",
    )
    sentence_node = WebNode(
        type="Sentence",
        identifier="(1)",
        citation="nbc.divA.part1.sect1.sent1",
        title="",
        path="",
        children=[clause_node],
    )
    mock_source = _mock_source(mock_source_cls)
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.sect1"}
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/section-1.json" if node is leaf else None
    )
    mock_source.fetch_content.return_value = {"id": "nbc.divA.part1.sect1"}
    mock_extract_images.return_value = []
    mock_extract_body.return_value = [("nbc.divA.part1.sect1", sentence_node)]

    _run(run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path)))

    mock_extract_body.assert_called_once_with(
        {"id": "nbc.divA.part1.sect1"}, {"root", "nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1"
    )
    assert leaf.children == [sentence_node]
    assert sentence_node.unified_number == "1.1.(1)"
    assert clause_node.unified_number == "1.1.(1)(a)"


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
    mock_write_json.assert_called_once_with(root, [], str(Path(tmp_path) / "bcbc_web.json"))


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
    mock_write_json.assert_called_once_with(root, [], str(Path(tmp_path) / "bcbc_web.json"))


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


def test_attach_notes_puts_part10_note_under_its_part_appendix():
    appendix = WebNode(
        type="part_appendix",
        identifier="",
        citation="nbc.divB.part10.sect4.appendix",
        title="",
        path="",
    )
    part = WebNode(
        type="part",
        identifier="10",
        citation="nbc.divB.part10",
        title="",
        path="",
        children=[appendix],
    )
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[part])
    content = {
        "id": "nbc.divB.part10.sect4.appendix",
        "application_notes": [
            {"id": "nbc.divB.part10.appendix.appnote1", "type": "application_note", "number": "10."}
        ],
    }
    citations = {"root", "nbc.divB.part10", "nbc.divB.part10.sect4.appendix"}

    widened = _attach_notes(root, [(appendix, content)], citations)

    assert [c.citation for c in appendix.children] == ["nbc.divB.part10.appendix.appnote1"]
    assert [c.type for c in part.children] == ["part_appendix"]
    assert "nbc.divB.part10.appendix.appnote1" in widened
