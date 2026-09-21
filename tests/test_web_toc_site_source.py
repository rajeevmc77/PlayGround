import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from web_toc.parsing.site_source import HttpxWebSource


def _fake_response(text, status_code=200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    is_json = text.strip().startswith("{")
    resp.json.return_value = json.loads(text) if is_json else None
    resp.raise_for_status = MagicMock()
    return resp


def _run(coro):
    return asyncio.run(coro)


def _mock_client(mock_client_cls):
    mock_client = AsyncMock()
    mock_client_cls.return_value = mock_client
    return mock_client


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_navigation_tree_requests_the_correct_url(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response('{"tree": []}')

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_navigation_tree()

    result = _run(scenario())

    mock_client.get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/navigation-tree.json"
    )
    assert result == {"tree": []}


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_content_builds_url_from_base_and_path(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response('{"id": "nbc.divA.part1.sect1"}')

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_content("/data/2024/content/nbc-diva/part-1/section-1.json")

    result = _run(scenario())

    mock_client.get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/content/nbc-diva/part-1/section-1.json"
    )
    assert result == {"id": "nbc.divA.part1.sect1"}


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_content_returns_none_for_html_fallback_response(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response("<!DOCTYPE html><html>...</html>")

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_content("/data/2024/content/bogus/nope.json")

    assert _run(scenario()) is None


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_content_returns_none_on_timeout(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.side_effect = httpx.ReadTimeout("timed out")

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_content("/data/2024/content/nbc-diva/part-1/section-1.json")

    assert _run(scenario()) is None


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_content_returns_none_on_connect_error(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.side_effect = httpx.ConnectError("boom")

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_content("/data/2024/content/nbc-diva/part-1/section-1.json")

    assert _run(scenario()) is None


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_image_builds_url_and_returns_bytes(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    resp = MagicMock()
    resp.content = b"\xff\xd8\xff\xe0fakejpegbytes"
    resp.raise_for_status = MagicMock()
    mock_client.get.return_value = resp

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_image("bc-graphics/gg00556a")

    result = _run(scenario())

    mock_client.get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/bc-graphics/gg00556a.jpg"
    )
    assert result == b"\xff\xd8\xff\xe0fakejpegbytes"


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_image_returns_none_on_http_error(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.side_effect = httpx.ConnectError("boom")

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_image("bc-graphics/missing")

    assert _run(scenario()) is None


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_fetch_image_returns_none_on_error_status(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    resp = MagicMock()
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    mock_client.get.return_value = resp

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_image("bc-graphics/missing")

    assert _run(scenario()) is None


@patch("web_toc.parsing.site_source.httpx.AsyncClient")
def test_context_manager_opens_and_closes_one_shared_client(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response('{"tree": []}')

    async def scenario():
        async with HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            await source.fetch_navigation_tree()
            await source.fetch_navigation_tree()

    _run(scenario())

    mock_client_cls.assert_called_once()
    mock_client.aclose.assert_awaited_once()
