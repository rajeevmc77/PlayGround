"""Renders live-site reading pages in a real headless browser.

The site is a client-rendered Next.js app - its reading-view markup only
exists after its own JavaScript has run - so a plain HTTP fetch returns an
empty shell. One Chromium instance and one browser context are shared for
the whole `async with` block; each fetch opens its own tab, so callers can
run many fetches concurrently (bounded by their own semaphore).
"""

from types import TracebackType
from typing import Protocol

from playwright.async_api import Browser, BrowserContext, Error, Playwright, async_playwright

from web_toc.domain.models import ScrapedPage

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


class PageSource(Protocol):
    async def fetch_page(self, url: str) -> ScrapedPage | None: ...
    async def fetch_nav_css(self, url: str, selector_pattern: str) -> list[dict]: ...


class PlaywrightPageSource:
    def __init__(self, ready_timeout_ms: int = 30000):
        self._ready_timeout_ms = ready_timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "PlaywrightPageSource":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        # Desktop width, so the site renders its desktop layout.
        self._context = await self._browser.new_context(viewport={"width": 1500, "height": 950})
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self._browser.close()
        await self._playwright.stop()

    async def fetch_page(self, url: str) -> ScrapedPage | None:
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="networkidle")
            await tab.wait_for_selector(READY_SELECTOR, timeout=self._ready_timeout_ms)
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
        )

    async def fetch_nav_css(self, url: str, selector_pattern: str) -> list[dict]:
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="networkidle")
            return await tab.evaluate(_NAV_CSS_JS, selector_pattern)
        finally:
            await tab.close()
