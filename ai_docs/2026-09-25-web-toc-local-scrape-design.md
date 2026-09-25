# Web TOC from locally scraped pages — design

Date: 2026-09-25

## Goal

Every node in `output/bcbc_web.json` carries (a) the **rendered text** the BC
Building Code website actually shows for it, and (b) a **location reference**
into a locally scraped copy of the site: which local page file, which element,
and that element's bounding box — the web counterpart of the PDF's
`page` + `bbox`.

Example — `B.9.38.1.1.Tbl1.Row2974.Col1` today:

| | `content` |
|---|---|
| `bcbc_pdf.json` | `9.23.5.5.Roof Trusses` (+ `page`, `bbox`) |
| `bcbc_web.json` | `[REF:internal:nbc.divBV2.part9.sect23.subsect5.art3.sent1:shortNum]` (no location) |

After this change the web cell holds the text the site renders there, plus
(values illustrative — the real xpath/bbox come from the layout pass):

```json
"location": {
  "page_file": "web_pages/nbc.divBV2.part9.sect38.html",
  "xpath": "/html/body/main/div/main/div/div/div/div[1]/…/table/tbody/tr[2973]/td[1]",
  "bbox": {"x0": 312.0, "y0": 88410.5, "x1": 540.0, "y1": 88436.0}
}
```

so the PDF page and the locally saved HTML can be rendered **side by side**,
each highlighting the same node.

## Why the web text is wrong today

`build_web_toc.py` builds from the site's **content JSON**, whose text contains
unresolved tokens (`[REF:internal:…:shortNum]`, `[REF:functional-statement:fs20]`,
`[REF:sub-objective:…]`). The site's own JavaScript resolves them at render
time (`9.3.1.1. General`, `F20 - OS2.1`). Only a rendered page has the real text.

## Findings that shape the design (measured 2026-09-25)

1. **The site lazy-loads long tables.** `/code/nbc.divBV2/9/38` first renders
   121 `<tr>` of Table 9.38.1.1.(1); each scroll to the last row appends 120 more
   (121 → 241 → 361 → …). The content JSON has 5,949 rows. The existing
   `output/web_pages/nbc.divBV2.part9.sect38.html` holds only the first 121 —
   **every current scrape of a long table is truncated.**
2. **JSON rows/cells align 1:1 with HTML `tr`/`td|th` by position.** Table rows
   in the JSON are `header_rows + body_rows`; on the 121 rows scraped, JSON row
   *i* is `tr` *i* and its cell count equals that `tr`'s `td|th` count on every
   row (rowspan/colspan cells are omitted from later rows in both). Rows and
   cells carry no HTML `id`.
3. **Sentences, clauses, subclauses, tables and table notes carry the site's
   own ids** in the HTML (`id="nbc.divBV2.part9.sect38.subsect1.art1.table1"`),
   identical to the JSON `id` = `WebNode.citation`.
4. **Saved pages reference assets under `/web-assets/…`** (see `page_html.py`)
   and size the reading panel to the viewport (`100vh`), so the panel — not the
   document — is the scroll container.

## Decisions (agreed with the user)

- **Location = local file + XPath + bbox measured on the rendered local page.**
- **Every location is rooted at the saved page's content panel,
  `/html/body/main/div/main`** (`main.ui-ContentPanel`; verified on the saved
  pages — `body > main#main-content > div.MainLayout > main.ui-ContentPanel`).
  That element is what the viewer renders beside the PDF page, so each `xpath`
  starts with it and each `bbox` is measured from its top-left corner.
- **Hybrid source:** the nav tree + content JSON still define structure (ids,
  numbering, table grid, owner resolution, `unified_number`); the scraped HTML
  supplies each node's `content` text and its location.
- **Scrape once, build offline:** `build_web_pages.py` is the only step that
  touches the network; `build_web_toc.py` reads only local files.
- **Read everything:** a table is not saved until its rendered row count equals
  the JSON's row count (all 5,949 rows for Table 9.38.1.1.(1)).

## Architecture

```
build_web_pages.py  (network)                       build_web_toc.py  (offline)
─────────────────────────────                       ──────────────────────────
navigation-tree.json ─► web_source/navigation.json ─┐
content JSON (per node) ─► web_source/content/*.json ├─► LocalWebSource ─► tree, notes,
live reading page ─► scroll to completion           │                     tables, body,
        └─► web_pages/<citation>.html ──────────────┤                     numbering
local server over web_pages/ ─► layout pass         │                         │
        └─► web_pages/<citation>.layout.json ───────┴──► layout_join ◄────────┘
                                                              └─► bcbc_web.json
                                                                  (content + location)
```

### 1. Scraping — `build_web_pages.py`

**1a. Source cache.** Using the existing `HttpxWebSource`:
- nav tree → `output/web_source/navigation.json`
- for every node where `content_url(node, version)` is not None (the same
  selection `build_web_toc.py` makes today) → `output/web_source/content/<citation>.json`.
  A missing/non-JSON response is recorded as absent (no file) and reported.
- image bytes stay downloaded where they are today (`web_images/`), now from
  `build_web_pages.py`, since it owns the network. `build_web_toc.py` only
  fills `local_path` for files that exist.

**1b. Scroll to completion.** `PlaywrightPageSource.fetch_page` gains a
completion step between the ready selector and capture:
- Expected row counts per table come from the cached content JSON
  (`table id → len(header_rows) + len(body_rows)`), passed in by the caller.
- Loop: for each table whose `#<id> tr` count is below expected, scroll its
  last `tr` into view and wait for the count to grow (poll up to a timeout).
  Also scroll the panel to its bottom until its `scrollHeight` is stable, for
  any non-table lazy content.
- Stops when every table reaches its expected count. If a table stops growing
  short of expected (after a bounded number of stalled attempts), the page is
  retried once in a fresh tab; if still short, the page is saved but reported
  as **incomplete** (table id, rendered vs expected rows) and the run exits
  non-zero at the end, so a truncated scrape is never silent.
- The pure decision logic ("which tables still need rows", "stalled?") lives
  in a small Playwright-free function so it is unit-testable with a fake page.

**1c. Layout pass.** After all pages are written and assets mirrored:
- Start a local static HTTP server (stdlib, background thread, ephemeral
  port) that serves `web_pages/*.html` at `/` and `web_pages/assets/` at
  `/web-assets/`, so pages render with the same CSS as in the viewer.
- Open each page in headless Chromium at the same 1500×950 viewport and, in
  one `evaluate`, collect:
  - `root`: the panel `/html/body/main/div/main` (the pass fails for a page
    where that XPath does not resolve to exactly one `main.ui-ContentPanel`)
  - `elements`: for every element with an `id` inside the root →
    `{id: {xpath, text, bbox}}`
  - `tables`: for every `table` inside an element with a table id →
    `{table_id: [[{xpath, text, bbox} per td|th] per tr]}` in document order
  - `images`: for every `img` inside the root → `{src, xpath, text: alt, bbox}`
    in document order
- `xpath` is an absolute, positional XPath that always begins
  `/html/body/main/div/main/…` (each step `tag[n]`, `n` = index among
  same-tag siblings), computed in the browser from the element up to the root —
  resolvable with `document.evaluate` in the viewer.
- `text` is the element's `innerText` with whitespace collapsed.
- **Coordinate system:** CSS pixels at the 1500px viewport width, origin at
  the top-left of the root panel `/html/body/main/div/main`, in its fully
  scrolled-out content space: `bbox = {x0, y0, x1, y1}` =
  element rect − root rect, plus the scroll offsets of any scrolling element
  between them — so the value does not depend on where the page happened to be
  scrolled. Matches the PDF's `{x0,y0,x1,y1}` key shape.
- Written to `output/web_pages/<citation>.layout.json`.

### 2. Offline build — `build_web_toc.py`

**2a. `LocalWebSource`** (`web_toc/parsing/local_source.py`) implements the
read side of `WebSource` — `fetch_navigation_tree()` and `fetch_content(path)` —
from `output/web_source/`. `fetch_content` is keyed by citation (the caller
already has the node), returning None when the file is absent. `run()` no
longer opens `HttpxWebSource`, no longer downloads images.

**2b. `layout_join`** (`web_toc/parsing/layout_join.py`, pure — takes the
tree, images and a `{page_citation: layout dict}` mapping; no file I/O).
For each node, find the page it lives on — the nearest ancestor-or-self that
is a page target (`page_targets()`), which covers subsections/articles cut
from their section page — then:

| Node type | Match rule |
|---|---|
| Sentence, Clause, Subclause, Table, table note, Note (appnote), headings with an id | `layout.elements[node.citation]` |
| Row | `layout.tables[table.citation][row_index]` (bbox = union of its cells) |
| Cell | `layout.tables[table.citation][row_index][col_index]` |
| Part/Section/Subsection/Article | `layout.elements[node.citation]` if present |
| Image | the `img` in its owner's page whose `src` ends with the image's `src` |

On a match:
- `location = {page_file: "web_pages/<page>.html", xpath, bbox}`, both taken
  straight from the layout entry (a Row's `xpath` is its `tr`, its bbox the
  union of its cells).
- `content` is replaced by the rendered `text` for Cell, Sentence, Clause,
  Subclause and Note. (Sentence `text` is the sentence's own element text,
  which includes its clauses — the same containment the PDF sentence text has.)
  Titles/headings are untouched.

**Grid check:** if a table's rendered grid has a different number of rows, or
any row a different number of cells, than its JSON subtree, the build fails
with the table id and first mismatching row — positional joining must never
silently misalign. Missing page / missing id / missing layout file: node keeps
its JSON content, gets no `location`, and is counted.

**2c. Model + writer.** `WebNode` and `WebImage` gain
`location: dict | None = None`; `json_writer` drops the key when None (same
pattern as `_drop_empty_headings`).

**2d. Report.** The build ends by printing located / unlocated counts per node
type and the list of pages with no layout file.

## Error handling summary

| Situation | Behaviour |
|---|---|
| Table still short after retry | page saved, reported incomplete, `build_web_pages.py` exits non-zero |
| Content JSON missing for a node | reported; node gets no structure from it (same as today) |
| Page/layout file missing | warning; nodes keep JSON content, no `location` |
| Id not in layout | node unlocated, counted in report |
| Table grid shape ≠ JSON | `build_web_toc.py` fails with table id + row |

## Testing (TDD)

- `scroll_plan` pure logic: tables below expected, growth, stall detection, all complete, no tables, expected-zero.
- Source cache: writes navigation + per-citation content, skips absent responses (fake `WebSource`).
- Layout pass: one `slow` Playwright test over a tiny local HTML fixture with the real `body > main > div > main` shell, served by the local server (ids, table grid, img, every xpath starts `/html/body/main/div/main` and resolves back to the same element, bbox relative to the root and independent of scroll position, missing root fails).
- Local server: serves pages at `/` and assets at `/web-assets/`, 404 otherwise.
- `LocalWebSource`: present / absent files.
- `layout_join`: id match; row/cell positional match; subsection resolved to its section page; image by src; missing page; missing id; grid-shape mismatch raises; content replaced only for the listed types.
- `json_writer`: `location` omitted when None, kept when set.
- Real-data check before the full run: scrape `nbc.divBV2.part9.sect38` alone and assert all 5,949 rows are present and `B.9.38.1.1.Tbl1.Row2974.Col1` has resolved text and a bbox; then run all ~136 pages.

## Findings from the real run (2026-09-25) and the refinements they forced

1. **Content JSON is revisioned.** ~250 items (rows, sentences, clauses,
   notes, articles) carry `revised: true` + `revisions` (an `original` and
   dated amendments, some `deleted`). Their own fields hold the *current*
   version, while the pages are rendered for `--date` (2024-03-08).
   `web_toc/parsing/revisions.py` reads the JSON as of that date in both
   builds; `build_web_pages.py` records it in `web_source/snapshot.json`. An
   item whose in-effect version is empty (an `original` placeholder for
   something a later amendment added) or `deleted` is dropped.
2. **Wide tables are split** into a header `<table>`, a `--pinned-col`
   duplicate of it, and a body `<table>`. `layout_script.GRID_ROWS_JS`
   (shared by the scraper's row count and the layout pass) concatenates
   header + body rows and skips the duplicate and cell-nested tables.
3. **Header-row span placeholders.** In 22 of 331 tables a header row's JSON
   has empty cells for span-covered positions the site doesn't render. Row
   counts must still match exactly (else the build fails), but within a row
   cells are paired left to right skipping *empty* JSON cells, and only if
   every non-empty cell is paired; otherwise the row's cells stay unlocated
   and are listed. 5 rows remain unpaired.
4. **Rendered text includes CSS-generated content** (the `[ … ]` around each
   compound reference is `::before`/`::after`), so the layout pass walks the
   DOM with computed styles instead of using `innerText`.
5. **Headings have no ids**; Part/Section/Subsection/Article are matched by
   `heading` number against their page's `h1–h6` text.

Result on the full site: 136/136 pages, every table fully loaded (Table
9.38.1.1.(1): 5,949 rows), located — 100% of rows, tables, figures, notes,
clauses, subclauses, parts, sections, subsections; 49,158/49,225 cells;
5,057/5,058 sentences; 2,015/2,022 articles. The unlocated ones are nav nodes
that did not exist yet on the snapshot date (e.g. 3.2.10.x) and front-matter
pages without numbered headings. 4 nodes still carry `[REF:` tokens, all
unlocated.

## Out of scope

- **Row/Cell keys across sources don't line up.** The PDF splits Table
  9.38.1.1.(1) into 5,861 rows, the web into 5,949, so `Row2974` is a
  different row in each file. This change fixes the web *text*, not the
  cross-source row numbering — a separate follow-up.
- Viewer changes (the side-by-side PDF/HTML render that consumes `location`).
- `app.py`, `check_directory_access.py`, the PDF pipeline.
