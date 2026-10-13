"""EquationRenderer's wiring with Playwright faked out - no browser, no
MathJax download. The real-browser behaviour is in
test_web_toc_equation_renderer.py (slow: it fetches MathJax from cdnjs)."""

import asyncio
from unittest.mock import patch

import pytest
from playwright.async_api import Error as PlaywrightError

from web_toc.domain.models import EquationSource
from web_toc.parsing.equation_renderer import EquationRenderer


class _FakeLocator:
    def __init__(self, page):
        self._page = page

    async def screenshot(self, path, timeout):
        self._page.screenshots.append(path)


class _FakePage:
    """Answers the startup evaluate with None and every typeset evaluate with
    `outcome` (or raises it, when it is an exception)."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.markups = []
        self.screenshots = []

    async def set_content(self, _html):
        return None

    async def wait_for_function(self, _expression):
        return None

    async def evaluate(self, _script, *args):
        if not args:
            return None
        self.markups.append(args[0])
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def locator(self, _selector):
        return _FakeLocator(self)


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_context(self, **_options):
        return self

    async def new_page(self):
        return self._page

    async def close(self):
        return None


class _FakePlaywright:
    def __init__(self, page):
        self.chromium = self
        self._page = page

    async def launch(self):
        return _FakeBrowser(self._page)

    async def stop(self):
        return None

    async def start(self):
        return self


def _run(page, source, path):
    async def go():
        async with EquationRenderer() as renderer:
            await renderer.render(source, path)

    target = "web_toc.parsing.equation_renderer.async_playwright"
    with patch(target, return_value=_FakePlaywright(page)):
        asyncio.run(go())


def _render_with(outcome, source, path):
    page = _FakePage(outcome)
    _run(page, source, path)
    return page


_MATHML = EquationSource(latex="x", mathml="<math><mi>x</mi></math>")


def test_a_typeset_that_comes_back_ok_is_screenshotted_to_the_output_path(tmp_path):
    page = _render_with("ok", _MATHML, tmp_path / "eq.png")
    assert page.screenshots == [str(tmp_path / "eq.png")]


@pytest.mark.parametrize("outcome", ["error", "no-container"])
def test_a_failed_typeset_raises_before_any_screenshot(tmp_path, outcome):
    page = _FakePage(outcome)
    with pytest.raises(ValueError, match=outcome):
        _run(page, _MATHML, tmp_path / "eq.png")
    assert page.screenshots == []


def test_a_playwright_error_while_typesetting_becomes_a_value_error(tmp_path):
    page = _FakePage(PlaywrightError("Execution context was destroyed"))
    with pytest.raises(ValueError, match="did not typeset") as raised:
        _run(page, _MATHML, tmp_path / "eq.png")
    assert isinstance(raised.value.__cause__, PlaywrightError)
    assert page.screenshots == []


def test_mathml_is_typeset_in_preference_to_latex(tmp_path):
    source = EquationSource(latex="y", mathml="<math><mi>x</mi></math>")
    page = _render_with("ok", source, tmp_path / "eq.png")
    assert page.markups == ["<math><mi>x</mi></math>"]


def test_latex_alone_is_display_wrapped_escaped_and_its_double_backslashes_collapsed(tmp_path):
    # The site double-escapes some commands; "<" and "&" are escaped because
    # the markup goes in through innerHTML before MathJax reads it as text.
    source = EquationSource(latex="a\\\\times b < c & d")
    page = _render_with("ok", source, tmp_path / "eq.png")
    assert page.markups == ["\\[a\\times b &lt; c &amp; d\\]"]
