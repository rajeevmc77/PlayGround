from unittest.mock import MagicMock, patch

from web_toc.parsing.site_source import HttpxWebSource


def _fake_response(text, status_code=200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    is_json = text.strip().startswith("{")
    resp.json.return_value = __import__("json").loads(text) if is_json else None
    resp.raise_for_status = MagicMock()
    return resp


@patch("web_toc.parsing.site_source.httpx.get")
def test_fetch_navigation_tree_requests_the_correct_url(mock_get):
    mock_get.return_value = _fake_response('{"tree": []}')
    source = HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024")

    result = source.fetch_navigation_tree()

    mock_get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/navigation-tree.json", timeout=30.0
    )
    assert result == {"tree": []}


@patch("web_toc.parsing.site_source.httpx.get")
def test_fetch_content_builds_url_from_base_and_path(mock_get):
    mock_get.return_value = _fake_response('{"id": "nbc.divA.part1.sect1"}')
    source = HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024")

    result = source.fetch_content("/data/2024/content/nbc-diva/part-1/section-1.json")

    mock_get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/content/nbc-diva/part-1/section-1.json",
        timeout=30.0,
    )
    assert result == {"id": "nbc.divA.part1.sect1"}


@patch("web_toc.parsing.site_source.httpx.get")
def test_fetch_content_returns_none_for_html_fallback_response(mock_get):
    mock_get.return_value = _fake_response("<!DOCTYPE html><html>...</html>")
    source = HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024")

    assert source.fetch_content("/data/2024/content/bogus/nope.json") is None
