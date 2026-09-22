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
def test_context_manager_launches_chromium_and_loads_mathjax_once(mock_sync_playwright):
    mock_playwright, mock_browser, mock_page = _mock_sync_playwright(mock_sync_playwright)

    with MathJaxRenderer():
        mock_playwright.chromium.launch.assert_called_once()
        mock_page.set_content.assert_called_once()
        html = mock_page.set_content.call_args[0][0]
        assert '<meta charset="utf-8">' in html
        assert 'id="equation-target"' in html

    mock_browser.close.assert_called_once()
    mock_playwright.stop.assert_called_once()


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_context_manager_waits_for_mathjax_startup(mock_sync_playwright):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)

    with MathJaxRenderer():
        pass

    mock_page.wait_for_function.assert_called_once()
    assert "MathJax.startup" in mock_page.wait_for_function.call_args[0][0]


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_retypesets_the_same_element_instead_of_reloading_the_page(
    mock_sync_playwright, tmp_path
):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_MATHML, target)

    # set_content is only ever called once, at __enter__ time - a second,
    # per-equation page reload is what caused every equation after the first
    # to silently time out (MathJax's auto-render never refires for it).
    mock_page.set_content.assert_called_once()
    script, mathml_arg = mock_page.evaluate.call_args[0]
    assert "typesetPromise" in script
    assert mathml_arg == _MATHML


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_screenshots_the_target_elements_container(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    mock_locator = MagicMock()
    mock_page.locator.return_value = mock_locator
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_MATHML, target)

    mock_page.locator.assert_called_once_with("#equation-target mjx-container")
    mock_locator.screenshot.assert_called_once_with(path=str(target), timeout=10_000)


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_raises_value_error_when_typeset_times_out(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    mock_page.evaluate.side_effect = [None, PlaywrightError("Timeout in typesetPromise")]
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer, pytest.raises(ValueError):
        renderer.render(_MATHML, target)


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_raises_value_error_when_container_never_appears(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)
    mock_locator = MagicMock()
    mock_locator.screenshot.side_effect = PlaywrightError("Timeout waiting for element")
    mock_page.locator.return_value = mock_locator
    target = tmp_path / "eq.png"

    with MathJaxRenderer() as renderer, pytest.raises(ValueError):
        renderer.render(_MATHML, target)


@patch("equation_export.rendering.mathjax_renderer.sync_playwright")
def test_render_can_be_called_multiple_times_on_the_same_page(mock_sync_playwright, tmp_path):
    _, _, mock_page = _mock_sync_playwright(mock_sync_playwright)

    with MathJaxRenderer() as renderer:
        renderer.render(_MATHML, tmp_path / "eq1.png")
        renderer.render(_MATHML, tmp_path / "eq2.png")

    mock_page.set_content.assert_called_once()
    assert mock_page.locator.return_value.screenshot.call_count == 2
