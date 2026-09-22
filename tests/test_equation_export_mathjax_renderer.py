from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import Error as PlaywrightError

from equation_export.rendering.mathjax_renderer import MathJaxRenderer

_MATHML = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>N</mi></math>'


def _mock_sync_playwright(mock_sync_playwright):
    mock_page = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser
    mock_sync_playwright.return_value.start.return_value = mock_playwright
    return mock_playwright, mock_browser, mock_page


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_context_manager_launches_and_closes_chromium(mock_sync_playwright):
    mock_playwright, mock_browser, _ = _mock_sync_playwright(mock_sync_playwright)

    with MathJaxRenderer():
        mock_playwright.chromium.launch.assert_called_once()

    mock_browser.close.assert_called_once()
    mock_playwright.stop.assert_called_once()


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_sets_page_content_with_mathml_and_utf8_charset(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_MATHML, target)

    html = mock_page.set_content.call_args[0][0]
    assert '<meta charset="utf-8">' in html
    assert _MATHML in html


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_waits_for_typeset_then_screenshots_the_container(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    mock_locator = MagicMock()
    mock_page.locator.return_value = mock_locator
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_MATHML, target)

    mock_page.wait_for_selector.assert_called_once_with("mjx-container", timeout=10_000)
    mock_page.locator.assert_called_once_with("mjx-container")
    mock_locator.screenshot.assert_called_once_with(path=str(target))


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_raises_value_error_when_typeset_times_out(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    mock_page.wait_for_selector.side_effect = PlaywrightError("Timeout waiting for selector")
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer, pytest.raises(ValueError):
        renderer.render(_MATHML, target)

    mock_page.locator.assert_not_called()
