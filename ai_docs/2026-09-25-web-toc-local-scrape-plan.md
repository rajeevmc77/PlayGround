# Web TOC from locally scraped pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bcbc_web.json` nodes carry the site's rendered text and a `location`
(`page_file`, `xpath` rooted at `/html/body/main/div/main`, `bbox`) into locally
scraped pages; `build_web_toc.py` runs fully offline.

**Architecture:** `build_web_pages.py` caches nav + content JSON, renders every
page scrolled to completion (row counts checked against the JSON), saves it,
then runs a Chromium layout pass over the saved pages (served by a local
static server) into `<citation>.layout.json`. `build_web_toc.py` builds the
tree from the cache and a pure `layout_join` fills `content` + `location`.

**Tech Stack:** Python 3.11, Playwright (Chromium), httpx, stdlib `http.server`, pytest.

**Spec:** `ai_docs/2026-09-25-web-toc-local-scrape-design.md`

## Global Constraints

- Location root XPath: `/html/body/main/div/main` (must resolve to exactly one `main.ui-ContentPanel`).
- Viewport for render + layout: 1500×950.
- bbox keys `{x0, y0, x1, y1}`, CSS px, origin = root panel top-left, scroll-independent.
- Local asset prefix `/web-assets` (`page_html.ASSET_PREFIX`).
- Functions ≤20 executable lines, CC ≤6, nesting ≤2; ruff line length 100.
- DoD: `ruff check --fix . && ruff format .`, `radon cc -s -n B` clean on touched code, `vulture`, `pytest`.

**Spec refinement:** headings have no HTML ids, so Part/Section/Subsection/
Article nodes are located by matching `node.heading` against the page's
`h1–h4` text (`^(?:Section\s+)?<heading>(?!\d|\.\d)`); layout rows are stored
as `{xpath, text, bbox, cells: [...]}` so a Row gets its own `tr` bbox.

## File map

| File | Change |
|---|---|
| `src/web_toc/domain/models.py` | `location` on WebNode/WebImage; `incomplete` on ScrapedPage |
| `src/web_toc/output/json_writer.py` | drop `location` when None |
| `src/web_toc/parsing/table_extractor.py` | `table_row_counts(content)` |
| `src/web_toc/parsing/scroll_plan.py` (new) | pure: which tables are short |
| `src/web_toc/parsing/page_source.py` | `fetch_page(url, expected_rows)` scrolls to completion |
| `src/web_toc/output/source_cache.py` (new) | write nav + content JSON cache |
| `src/web_toc/parsing/local_source.py` (new) | `LocalWebSource` reading the cache |
| `src/web_toc/parsing/local_page_server.py` (new) | static server for saved pages |
| `src/web_toc/parsing/layout_source.py` (new) | Chromium layout pass |
| `src/web_toc/parsing/layout_join.py` (new) | pure join of layout into tree/images |
| `src/build_web_pages.py` | cache → render → save → assets → images → layout |
| `src/build_web_toc.py` | offline build + join + report |

## Tasks

### Task 1: `location` field + writer
- Test (`tests/test_web_toc_json_writer.py`): node/image with `location=None` → key absent; with a dict → kept verbatim.
- Impl: `location: dict | None = None` on `WebNode`, `WebImage`; `ScrapedPage.incomplete: dict[str, list[int]] = {}`; writer pops `location` when None (recursive, alongside `_drop_empty_headings`).

### Task 2: `table_row_counts`
- Test: nested tables → `{id: len(header_rows)+len(body_rows)}`; table without id skipped; empty content → `{}`.
- Impl in `table_extractor.py` reusing `_walk_tables`.

### Task 3: scroll plan + scroll-to-completion
- Pure `short_tables(rendered: dict[str,int], expected: dict[str,int]) -> dict[str, list[int]]` (`{id: [rendered, expected]}` for rendered < expected; a table missing from the DOM counts as 0).
- `PlaywrightPageSource.fetch_page(url, expected_rows=None)`: after ready selector, loop — count `tr` per expected table (`document.getElementById(id).querySelectorAll('tr')`), stop when `short_tables` empty; else scroll each short table's last `tr` into view and `wait_for_function` for growth (timeout → stall; `MAX_STALLS = 3` consecutive stalls ends the loop). Result `ScrapedPage.incomplete = short_tables(...)`.
- Test: file:// fixture page that appends 5 rows each time its last row scrolls into view (IntersectionObserver), up to 23 → `fetch_page(url, {"t1": 23})` captures 23 `<tr>`, `incomplete == {}`; expected 30 → `incomplete == {"t1": [23, 30]}`.

### Task 4: source cache + `LocalWebSource`
- `cache_sources(http, root, version, source_dir) -> dict[str, dict]`: writes `navigation.json` (caller passes the raw nav) and `content/<citation>.json` for each `content_url` node, concurrency-bounded; absent responses skipped + reported. Citation file names validated with `page_writer.page_file`-style regex.
- `LocalWebSource(source_dir)`: `fetch_navigation_tree() -> dict`, `fetch_content(citation) -> dict | None`, `content_citations() -> list[str]`.
- Tests with fake http + tmp dirs, including missing file → None and unsafe citation refused.

### Task 5: local page server + layout pass
- `serve_pages(pages_dir) -> contextmanager[str base_url]`: `ThreadingHTTPServer` on 127.0.0.1:0 in a daemon thread; `/<name>.html` → `pages_dir/<name>.html`, `/web-assets/<p>` → `asset_file(pages_dir/"assets", "/<p>")`; everything else 404.
- `PlaywrightLayoutSource.measure(url) -> dict | None` runs `_LAYOUT_JS`, returning `{"elements": {id: {xpath,text,bbox}}, "tables": {id: [{xpath,text,bbox,cells:[{xpath,text,bbox}]}]}, "images": [{src,xpath,text,bbox}], "headings": [{xpath,text,bbox}]}` or None when the root XPath doesn't resolve to one `main.ui-ContentPanel`.
- Tests: server serves page/asset/404 and refuses `..`; layout over a fixture with the real shell: xpaths start with root and `document.evaluate` back to the same element, table grid shape, img, heading list, bbox relative to root (panel offset by a margin → y0 still relative), missing root → None.

### Task 6: `build_web_pages.py` wiring
- Order: nav → `cache_sources` → page targets → render with `expected_rows = table_row_counts(contents.get(citation, {}))`, retry once when `incomplete` → save pages → mirror assets → download images (extract_images over cached contents) → layout pass over saved pages → `<citation>.layout.json`.
- `run()` returns the incomplete map; `main()` prints it and exits 1 if non-empty.
- Tests: extend fakes (`fetch_page(url, expected_rows)`, `fetch_content`, fake layout source); retry on incomplete; incomplete reported; layout files written; nav/content cache written.

### Task 7: `layout_join`
- `join_layout(root, images, layouts: dict[str, dict], page_citations: set[str]) -> dict[str, dict[str,int]]` (report: `{type: {"located": n, "unlocated": n}}`).
- Page of a node = nearest ancestor-or-self whose citation is in `page_citations`.
- Rules: id match (Sentence/Clause/Subclause/Table/Note + any node whose citation is an element id); heading match for part/section/subsection/article; Row/Cell positional under their Table; image by `src == f"/web-assets/{image.src}.jpg"` on the owner's page.
- Content replaced by rendered text for Cell, Sentence, Clause, Subclause, Note.
- `GridMismatch(ValueError)` raised with table id + first bad row when row count or any row's cell count differs.
- Tests: each rule, missing page, missing id, grid mismatch, content untouched for Table/headings, report counts.

### Task 8: `build_web_toc.py` offline
- Replace `HttpxWebSource` with `LocalWebSource`; drop `download_images`; set `image.local_path` when `web_images/<id>.jpg` exists; load `web_pages/*.layout.json`; call `join_layout`; print report.
- Update `tests/test_build_web_toc.py` for the offline source (fake local source; no network patching).

### Task 9: real data + docs + DoD
- Scrape only `nbc.divBV2.part9.sect38` (`--only` citation filter on `build_web_pages.py`), assert 5,949 `tr`, join, check `B.9.38.1.1.Tbl1.Row2974.Col1`.
- Full scrape + build; report counts.
- Update CLAUDE.md working notes (offline build, `web_source/`, `layout.json`, location shape).
- DoD checklist, commit, PR.
