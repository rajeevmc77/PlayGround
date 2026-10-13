"""Renders one equation's real source (mathml, or latex as a fallback) to a
standalone PNG via a headless-browser MathJax typeset - the same MathJax
build the live site loads, so the rendered glyphs match what a visitor
sees, independent of any particular page's own on-screen rendering."""

import html
from pathlib import Path
from types import TracebackType

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from web_toc.domain.models import EquationSource

_MATHJAX_SCRIPT_URL = "https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.js"
_TYPESET_TIMEOUT_MS = 10_000
_TARGET_ELEMENT_ID = "equation-target"
# The screenshot is of the whole target, not of the mjx-container: an inline
# container's box is only its line's height, so a fraction or root standing
# taller than the line was cut off at the top and bottom. The inline-block
# target's line box takes in every glyph box; the padding keeps a blank
# border round the formula, and a display container's own 1em vertical margin
# is dropped so it doesn't pad the image.
_TARGET_SELECTOR = f"#{_TARGET_ELEMENT_ID}"
_TARGET_STYLE = f"""#{_TARGET_ELEMENT_ID} {{ display: inline-block; padding: 2px; }}
#{_TARGET_ELEMENT_ID} mjx-container[display="true"] {{ margin: 0; }}"""

# typeset:false skips the (nonexistent, at load time) initial auto-typeset -
# each equation is typeset explicitly via typesetPromise below instead.
# Dropping the bundle's noundefined package makes an unknown control sequence a real
# merror instead of silently-red literal text that would look like a result.
_PAGE_HTML = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script>
window.MathJax = {{
    startup: {{ typeset: false }},
    tex: {{ packages: {{'[-]': ['noundefined']}} }}
}};
</script>
<script src="{_MATHJAX_SCRIPT_URL}"></script>
<style>
{_TARGET_STYLE}
</style>
</head>
<body style="margin:0; padding: 20px; display: inline-block;">
<div id="{_TARGET_ELEMENT_ID}"></div>
</body>
</html>
"""

# typesetClear drops MathJax's bookkeeping for whatever this element held
# before, so replacing its content and re-typesetting doesn't get skipped as
# "already processed". MathJax renders a TeX/MathML error in place (an
# mjx-merror / data-mjx-error node) and still emits a container, so the
# outcome is read back here rather than inferred from the container existing.
_TYPESET_SCRIPT = f"""async (markup) => {{
    const target = document.getElementById("{_TARGET_ELEMENT_ID}");
    MathJax.typesetClear([target]);
    target.innerHTML = markup;
    await MathJax.typesetPromise([target]);
    if (!target.querySelector("mjx-container")) return "no-container";
    if (target.querySelector("mjx-merror, [data-mjx-error]")) return "error";
    return "ok";
}}"""


def _normalize_latex(latex: str) -> str:
    """The site's own latex export double-escapes some commands (two
    literal backslashes before e.g. `times`/`leq`) - confirmed by comparing
    against the same entry's plainText field. Collapse back to the single
    backslash MathJax expects."""
    return latex.replace("\\\\", "\\")


def _as_markup(source: EquationSource) -> str:
    """mathml is already a `<math>` element MathJax recognizes directly; a
    latex-only fallback is wrapped in MathJax's `\\[ ... \\]` display
    delimiters (a `<script type="math/tex">` injected via innerHTML is never
    picked up by MathJax v3). The latex is HTML-escaped first because it is
    parsed as markup before MathJax reads the resulting text."""
    if source.mathml is not None:
        return source.mathml
    return "\\[" + html.escape(_normalize_latex(source.latex), quote=False) + "\\]"


class EquationRenderer:
    """One shared headless-browser MathJax instance for the lifetime of an
    `async with` block; each equation is retypeset into the same element via
    MathJax's own typesetClear/typesetPromise API. Reloading the whole page
    (and refetching the multi-megabyte MathJax bundle) per equation only
    auto-typeset the first one - MathJax's auto-render never re-triggers on
    a later set_content call, so every equation after the first would time
    out waiting for a container that was never going to appear."""

    def __init__(self, device_scale_factor: float = 1):
        self._device_scale_factor = device_scale_factor
        self._playwright = None
        self._browser = None
        self._page = None

    async def __aenter__(self) -> "EquationRenderer":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        context = await self._browser.new_context(device_scale_factor=self._device_scale_factor)
        self._page = await context.new_page()
        await self._page.set_content(_PAGE_HTML)
        await self._page.wait_for_function(
            "window.MathJax && MathJax.startup && MathJax.startup.promise"
        )
        await self._page.evaluate("() => MathJax.startup.promise")
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self._browser.close()
        await self._playwright.stop()

    async def render(self, source: EquationSource, output_path: Path) -> None:
        assert self._page is not None
        markup = _as_markup(source)
        try:
            outcome = await self._page.evaluate(_TYPESET_SCRIPT, markup)
            if outcome != "ok":
                raise ValueError(f"MathJax did not typeset ({outcome}): {markup!r}")
            await self._page.locator(_TARGET_SELECTOR).screenshot(
                path=str(output_path), timeout=_TYPESET_TIMEOUT_MS
            )
        except PlaywrightError as exc:
            raise ValueError(f"MathJax did not typeset: {markup!r}") from exc
