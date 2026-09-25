"""Renders live-site reading pages in a real headless browser.

The site is a client-rendered Next.js app - its reading-view markup only
exists after its own JavaScript has run - so a plain HTTP fetch returns an
empty shell. One Chromium instance and one browser context are shared for
the whole `async with` block; each fetch opens its own tab, so callers can
run many fetches concurrently (bounded by their own semaphore).
"""

from types import TracebackType
from typing import Protocol

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from web_toc.domain.models import EquationCapture, ScrapedPage
from web_toc.parsing.equation_script import (
    GLYPHS_SELECTOR,
    MARK_EQUATIONS_JS,
    MARKED_SELECTOR,
    SWAP_EQUATIONS_JS,
)
from web_toc.parsing.layout_script import GRID_ROWS_JS, LAYOUT_JS
from web_toc.parsing.scroll_plan import short_tables

READY_SELECTOR = "main.ui-ContentPanel .reading-view__content, main.ui-ContentPanel .partRenderer"

_CAPTURE_JS = """() => ({
  panel: document.querySelector('main.ui-ContentPanel').outerHTML,
  title: document.title,
  stylesheets: [...document.querySelectorAll('link[rel=stylesheet]')]
    .map((link) => link.getAttribute('href')),
  inlineStyles: [...document.querySelectorAll('head style')].map((s) => s.textContent),
})"""

# Walks the CSSOM rather than raw stylesheet text so @media/@supports
# nesting comes back already parsed: a matching rule inside an at-rule is
# re-wrapped in just that at-rule. :root custom properties and @font-face
# are always kept - the matched rules depend on both.
_NAV_CSS_JS = """(pattern) => {
  const re = new RegExp(pattern);
  const out = [];
  const keep = (rule) => rule.selectorText
    ? re.test(rule.selectorText) || rule.selectorText === ':root'
    : rule.constructor.name === 'CSSFontFaceRule';
  const walk = (rules, href, wrap) => {
    for (const rule of rules) {
      if (rule.cssRules && !rule.selectorText) {
        const cond = rule.conditionText || (rule.media && rule.media.mediaText) || '';
        walk(rule.cssRules, href, (css) => wrap(`@media ${cond} { ${css} }`));
      } else if (keep(rule)) {
        out.push({ href, css: wrap(rule.cssText) });
      }
    }
  };
  for (const sheet of document.styleSheets) {
    const href = sheet.href ? new URL(sheet.href).pathname : '/';
    try { walk(sheet.cssRules, href, (css) => css); } catch (e) { /* cross-origin */ }
  }
  return out;
}"""


# A table's id sits on its wrapping block, not on a <table>; its rows are
# counted the same way the layout pass reads them (layout_script.gridRows).
_TABLE_JS = f"""{GRID_ROWS_JS}
const rowsOf = (id) => {{
  const block = document.getElementById(id);
  return block ? gridRows(block) : [];
}};"""

_ROW_COUNTS_JS = f"""(ids) => {{ {_TABLE_JS}
  return Object.fromEntries(ids.map((id) => [id, rowsOf(id).length]));
}}"""

# Jumps a few rows back first, so the last row re-enters the viewport even
# when it was already visible - the site loads more on that transition.
_SCROLL_LAST_ROWS_JS = f"""(ids) => {{ {_TABLE_JS}
  for (const id of ids) {{
    const rows = rowsOf(id);
    if (!rows.length) continue;
    rows[Math.max(0, rows.length - 10)].scrollIntoView();
    rows[rows.length - 1].scrollIntoView();
  }}
}}"""

_GREW_JS = f"""([ids, before]) => {{ {_TABLE_JS}
  return ids.some((id) => rowsOf(id).length > before[id]);
}}"""

# Consecutive scroll attempts with no new rows before a table is given up on.
MAX_STALLS = 3


class PageSource(Protocol):
    async def fetch_page(
        self, url: str, expected_rows: dict[str, int] | None = None
    ) -> ScrapedPage | None: ...
    async def fetch_nav_css(self, url: str, selector_pattern: str) -> list[dict]: ...
    async def fetch_layout(self, url: str) -> dict | None: ...
    async def capture_equations(self, url: str) -> EquationCapture | None: ...


async def _row_counts(tab: Page, expected: dict[str, int]) -> dict[str, list[int]]:
    return short_tables(await tab.evaluate(_ROW_COUNTS_JS, list(expected)), expected)


async def _screenshot_equations(tab: Page, keys: list[str]) -> dict[str, bytes]:
    """One PNG per distinct key, of the first block marked with it."""
    blocks = tab.locator(MARKED_SELECTOR)
    images: dict[str, bytes] = {}
    for index, key in enumerate(keys):
        if key not in images:
            glyphs = blocks.nth(index).locator(GLYPHS_SELECTOR).first
            images[key] = await glyphs.screenshot()
    return images


class PlaywrightPageSource:
    def __init__(
        self,
        ready_timeout_ms: int = 30000,
        growth_timeout_ms: int = 10000,
        device_scale_factor: float = 1,
    ):
        self._ready_timeout_ms = ready_timeout_ms
        self._growth_timeout_ms = growth_timeout_ms
        # Only screenshots see it: CSS px (and so every bbox) are unchanged.
        self._device_scale_factor = device_scale_factor
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "PlaywrightPageSource":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        # Desktop width, so the site renders its desktop layout.
        self._context = await self._browser.new_context(
            viewport={"width": 1500, "height": 950},
            device_scale_factor=self._device_scale_factor,
        )
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self._browser.close()
        await self._playwright.stop()

    async def fetch_page(
        self, url: str, expected_rows: dict[str, int] | None = None
    ) -> ScrapedPage | None:
        """Renders `url`, first scrolling each table in `expected_rows`
        (table id -> row count from its content JSON) until the site has
        lazy-loaded all of them. Tables still short are left in
        `ScrapedPage.incomplete`."""
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="networkidle")
            await tab.wait_for_selector(READY_SELECTOR, timeout=self._ready_timeout_ms)
            incomplete = await self._load_all_rows(tab, expected_rows or {})
            data = await tab.evaluate(_CAPTURE_JS)
        except Error:
            return None
        finally:
            await tab.close()
        return ScrapedPage(
            panel=data["panel"],
            title=data["title"],
            stylesheets=data["stylesheets"],
            inline_styles=data["inlineStyles"],
            incomplete=incomplete,
        )

    async def _load_all_rows(self, tab: Page, expected: dict[str, int]) -> dict[str, list[int]]:
        stalls = 0
        short = await _row_counts(tab, expected)
        while short and stalls < MAX_STALLS:
            grew = await self._scroll_and_wait(tab, short)
            stalls = 0 if grew else stalls + 1
            short = await _row_counts(tab, expected)
        return short

    async def _scroll_and_wait(self, tab: Page, short: dict[str, list[int]]) -> bool:
        ids = list(short)
        before = {table_id: rendered for table_id, (rendered, _) in short.items()}
        await tab.evaluate(_SCROLL_LAST_ROWS_JS, ids)
        try:
            await tab.wait_for_function(
                _GREW_JS, arg=[ids, before], timeout=self._growth_timeout_ms
            )
        except PlaywrightTimeoutError:
            return False
        return True

    async def fetch_layout(self, url: str) -> dict | None:
        """Runs the layout pass (layout_script.py) over an already-saved,
        locally served page; None if it has no content panel."""
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="load")
            return await tab.evaluate(LAYOUT_JS)
        finally:
            await tab.close()

    async def capture_equations(self, url: str) -> EquationCapture | None:
        """Screenshots every MathJax equation on an already-saved, locally
        served page and swaps each for an <img> of itself (see
        equation_script.py); None if the page has none left to capture."""
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="load")
            await tab.evaluate("document.fonts.ready.then(() => null)")
            marked = await tab.evaluate(MARK_EQUATIONS_JS)
            if not marked:
                return None
            images = await _screenshot_equations(tab, [entry["key"] for entry in marked])
            return EquationCapture(html=await tab.evaluate(SWAP_EQUATIONS_JS), images=images)
        finally:
            await tab.close()

    async def fetch_nav_css(self, url: str, selector_pattern: str) -> list[dict]:
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="networkidle")
            return await tab.evaluate(_NAV_CSS_JS, selector_pattern)
        finally:
            await tab.close()
