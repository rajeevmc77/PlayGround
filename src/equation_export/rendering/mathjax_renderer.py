from pathlib import Path
from typing import Protocol

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# Same MathJax build the live site loads, so a MathML string typesets
# identically here as it does for a real visitor.
_MATHJAX_SCRIPT_URL = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.js"

_TYPESET_TIMEOUT_MS = 10_000


class MathmlRenderer(Protocol):
    def render(self, mathml: str, output_path: Path) -> None: ...


class MathJaxRenderer:
    """Renders a MathML string to a standalone PNG via a headless-browser
    MathJax typeset. Used as a fallback for equations whose `latex` field
    isn't real TeX (see `equation_needs_mathml_fallback`) - matplotlib's
    mathtext either raises or, worse, silently draws garbage for that input
    without raising, but the site's own MathML renders correctly because it
    was never routed through the broken latex in the first place."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "MathJaxRenderer":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._page = self._browser.new_page()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._browser.close()
        self._playwright.stop()

    def render(self, mathml: str, output_path: Path) -> None:
        assert self._page is not None
        self._page.set_content(_html_for(mathml))
        self._wait_for_typeset(mathml)
        self._page.locator("mjx-container").screenshot(path=str(output_path))

    def _wait_for_typeset(self, mathml: str) -> None:
        try:
            self._page.wait_for_selector("mjx-container", timeout=_TYPESET_TIMEOUT_MS)
        except PlaywrightError as exc:
            raise ValueError(f"MathJax did not typeset: {mathml!r}") from exc


def _html_for(mathml: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="{_MATHJAX_SCRIPT_URL}"></script>
</head>
<body style="margin:0; padding: 20px; display: inline-block;">
{mathml}
</body>
</html>
"""
