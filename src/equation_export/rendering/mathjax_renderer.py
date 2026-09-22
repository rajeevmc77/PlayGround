from pathlib import Path
from typing import Protocol

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# Same MathJax build the live site loads, so a MathML string typesets
# identically here as it does for a real visitor.
_MATHJAX_SCRIPT_URL = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.js"

_TYPESET_TIMEOUT_MS = 10_000
_TARGET_ELEMENT_ID = "equation-target"
_TARGET_SELECTOR = f"#{_TARGET_ELEMENT_ID} mjx-container"

# typeset:false skips the (nonexistent, at load time) initial auto-typeset -
# each equation is typeset explicitly via typesetPromise below instead.
_PAGE_HTML = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script>window.MathJax = {{ startup: {{ typeset: false }} }};</script>
<script src="{_MATHJAX_SCRIPT_URL}"></script>
</head>
<body style="margin:0; padding: 20px; display: inline-block;">
<div id="{_TARGET_ELEMENT_ID}"></div>
</body>
</html>
"""

# typesetClear drops MathJax's bookkeeping for whatever this element held
# before, so replacing its content and re-typesetting doesn't get skipped as
# "already processed".
_TYPESET_SCRIPT = f"""(mathml) => {{
    const target = document.getElementById("{_TARGET_ELEMENT_ID}");
    MathJax.typesetClear([target]);
    target.innerHTML = mathml;
    return MathJax.typesetPromise([target]);
}}"""


class MathmlRenderer(Protocol):
    def render(self, mathml: str, output_path: Path) -> None: ...


class MathJaxRenderer:
    """Renders a MathML string to a standalone PNG via a headless-browser
    MathJax typeset. Used as a fallback for equations whose `latex` field
    isn't real TeX (see `equation_needs_mathml_fallback`) - matplotlib's
    mathtext either raises or, worse, silently draws garbage for that input
    without raising, but the site's own MathML renders correctly because it
    was never routed through the broken latex in the first place.

    MathJax loads once for the lifetime of the `with` block; each equation
    is retypeset into the same element via MathJax's own
    typesetClear/typesetPromise API. Reloading the whole page (and
    refetching the multi-megabyte MathJax bundle) per equation only
    auto-typeset the first one - MathJax's auto-render never re-triggers on
    a later `set_content` call, so every equation after the first timed out
    waiting for a container that was never going to appear."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "MathJaxRenderer":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._page = self._browser.new_page()
        self._page.set_content(_PAGE_HTML)
        self._page.wait_for_function("window.MathJax && MathJax.startup && MathJax.startup.promise")
        self._page.evaluate("() => MathJax.startup.promise")
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._browser.close()
        self._playwright.stop()

    def render(self, mathml: str, output_path: Path) -> None:
        assert self._page is not None
        try:
            self._page.evaluate(_TYPESET_SCRIPT, mathml)
            self._page.locator(_TARGET_SELECTOR).screenshot(
                path=str(output_path), timeout=_TYPESET_TIMEOUT_MS
            )
        except PlaywrightError as exc:
            raise ValueError(f"MathJax did not typeset: {mathml!r}") from exc
