# BC Building Code (Web) — Table of Images — Design

## Goal

Extend the MO Package viewer with a fourth tab, sourced from the **live BC Building Code
website** (`https://dev.buildingcode.gov.bc.ca/?version=2024&date=2024-03-08`) rather than
the local PDF: a hierarchical Table of Images built from that site's own navigation tree and
per-section content, so a user can browse the official 2024 BC Building Code's figures by
where they live in the code (Division → Part → Section → Subsection → Article), and jump out
to the live page for full context.

This is purely additive. Nothing under `src/mo_toc/`, `src/build_mo_toc.py`, or their tests
changes behavior. `src/serve_mo_toc.py`, `index.html`, and `viewer.js` gain new routes/markup
only — the three existing tabs (Table of Contents, Images, Table of Images) keep their
current endpoints, JSON shape, and rendering logic untouched.

## The source site, as verified by direct inspection

- `GET /data/2024/navigation-tree.json` (~900 KB) — the whole document's hierarchy in one
  file. Every node has `id`, `type`, `title`, `path` (a client-side route), and optionally
  `number` and `children`. Node `type`s observed: `volume`, `division`, `part`, `section`,
  `subsection`, `article`, `part_appendix`, `division_appendix`, `spectables`, `index`,
  `conversions`. There are 2 `volume` entries at the top (Division B's Part 9 — Housing and
  Small Buildings — lives under its own second `volume`, `nbc.divBV2`, not under the main
  `nbc.divB`). No page numbers or coordinates exist — it's a web route, not a PDF.
- The tree itself carries **no article body or images**. Content is fetched separately, one
  JSON file per `section` / `part_appendix` / `division_appendix` / `spectables` /
  front-matter `article` node, and a `section`'s content JSON contains ALL of its nested
  subsections → articles → sentences → clauses → subclauses (and tables) in one payload —
  fetched once per section, not once per article.
- Inside that nested content, an image is a node shaped exactly like this (found nested
  inside a table cell in `/data/2024/content/nbc-divbv2/part-9/section-23.json`):
  ```json
  {
    "type": "figure",
    "id": "nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23",
    "source": "bc",
    "graphic": { "src": "bc-graphics/gg00556a", "alt_text": "Three storey building configuration" }
  }
  ```
  A figure's own `id` is always its full ancestor chain plus its own suffix — this is the
  key structural fact the whole design leans on: **no position-based owner matching is
  needed** (contrast with the PDF pipeline's `image_matcher.py`, which has to infer
  ownership from page/y-position because the PDF has no such IDs).
- The actual image bytes are plain static files: `https://dev.buildingcode.gov.bc.ca/{src}.jpg`
  (e.g. `.../bc-graphics/gg00556a.jpg`), confirmed by inspecting rendered `<img>` tags on a
  live article page. Public, no auth, no query params.
- The site is a Next.js app; any unmatched `/data/...` path returns **HTTP 200 with an HTML
  fallback page**, not a 404 — a real content JSON always starts with `{`. Every fetch in this
  design must check for that instead of trusting the status code.

### Content URL derivation (verified against the live site)

Only nodes that can directly contain a `figure` need a content fetch. Structural-only types
(`volume`, `division`, `part`, `subsection`) never do — figures always nest inside one of the
types below.

| Node type | Content URL | Verified example |
|---|---|---|
| `section` | `/data/2024/content/{div-slug}/part-{partNum}/section-{sectNum}.json` | `nbc-diva/part-1/section-1.json`, `nbc-divbv2/part-9/section-23.json` |
| `part_appendix` | `/data/2024/content/{div-slug}/part-{partNum}/appendix.json` | `nbc-diva/part-1/appendix.json` |
| `division_appendix` | `/data/2024/content/{div-slug}/appendix-{letter-lower}.json` | `nbc-divb/appendix-c.json` (Appendix C, climatic/seismic data — 3.1 MB) |
| `spectables` | `/data/2024/content/{div-slug}/part-{partNum}/spectables/{tableNum}.json` | `nbc-divbv2/part-9/spectables/1.json` |
| front-matter `article` (parent division id `nbc.2020.frontmatter`) | `/data/2024/content/front-matter/{lastPathSegment}.json` | `front-matter/preface.json`, where `lastPathSegment` is the tail of the node's own `path`, e.g. `/code/front-matter/preface` → `preface` |
| `index`, `conversions` | **skipped** — no content fetch | glossary/unit-conversion tables; no figures expected, and no working URL pattern was found in the time spent (guesses like `content/index/volume-2.json`, `content/conversions/2.json` all hit the HTML fallback). Out of scope for this feature. |

`{div-slug}` = the node's own division ancestor id, lowercased with `.` replaced by `-`
(`nbc.divA` → `nbc-diva`, `nbc.divBV2` → `nbc-divbv2`, `nbc.divC` → `nbc-divc`). `{partNum}`
and `{sectNum}`/`{tableNum}` are the numeric suffix already present in the node's own `id`
(`...part9...` → `9`, `...sect23...` → `23`).

Any fetch whose response doesn't start with `{` is treated as "no content available for this
node" — logged and skipped, not a hard failure. This keeps one wrong guess (there will be
some, given `index`/`conversions` were already wrong) from crashing the whole build.

### Owner assignment (much simpler than the PDF pipeline)

Because every figure's `id` already contains its full ancestor chain, ownership is a pure
string operation: **strip trailing dot-segments off the figure's `id` until the remainder
matches a node's own `citation`** (the citation set built while parsing `navigation-tree.json`
— i.e. every `section`/`subsection`/`article`/`part_appendix`/`division_appendix`/
`spectables`/front-matter-`article` id). This works identically whether the figure sits
directly under an article, or three levels deep inside a table cell — no bbox, no
page/y-position, no gap-tolerance heuristics.

## Architecture

A new, independent package, parallel to `mo_toc/` and following the same Clean Architecture
split (domain / parsing / output), plus additive changes to the existing web layer:

```
src/web_toc/
  __init__.py
  domain/
    models.py          # WebNode, WebImage — pure dataclasses, no HTTP/JSON specifics
  parsing/
    site_source.py      # WebSource protocol + HttpxWebSource implementation (uses httpx,
                         # already a dependency — no new package needed)
    tree_builder.py      # pure: navigation-tree.json dict -> WebNode tree
    content_url.py       # pure: WebNode -> content URL, or None for skipped types (the
                          # dispatch table above)
    image_extractor.py   # walks one content JSON's dict tree -> list[WebImage] with owner
                          # assignment (the strip-and-match algorithm above)
  output/
    json_writer.py       # writes output/web_toc.json: {"tree": WebNode, "images": [WebImage]}
src/build_web_toc.py      # CLI orchestrator, parallel to build_mo_toc.py:
                           #   fetch navigation tree -> build WebNode tree -> for each
                           #   content-bearing node, fetch content -> extract + attach images
                           #   -> write output/web_toc.json
```

### Domain model

```python
@dataclass
class WebNode:
    type: str              # "volume" | "division" | "part" | "section" | ... (table above)
    identifier: str        # printed number if any, e.g. "1.1.1.1"; "" for un-numbered nodes
    citation: str           # the site's own dotted id, e.g. "nbc.divA.part1.sect1.subsect1.art1"
    title: str
    path: str               # site route, e.g. "/code/nbc.divA/1/1/1/1" — used to build the
                             # live link-out URL
    children: list["WebNode"]

@dataclass
class WebImage:
    id: str                 # the figure's own id, e.g. "...art7.table1.row4.figure23"
    src: str                 # "bc-graphics/gg00556a" (no extension)
    alt_text: str
    owner_citation: str       # matches some WebNode.citation, via the strip-and-match rule
```

No bbox, no page number, no thumbnail path — the two fields the PDF pipeline needs for
rendering a highlight simply don't apply here. `image_url` (`https://dev.buildingcode.gov.bc.ca/{src}.jpg`)
is a display-time concern, not stored on the model.

### Build script behavior (`src/build_web_toc.py`)

```
python3 src/build_web_toc.py
    [--base-url https://dev.buildingcode.gov.bc.ca]   # overridable for testing
    [--version 2024] [--date 2024-03-08]
    [--output-dir output]
```

1. Fetch `/data/{version}/navigation-tree.json`, build the `WebNode` tree (`tree_builder.py`).
2. Walk the tree; for every node whose type has a content-URL rule, derive the URL
   (`content_url.py`), fetch it, and — if it parses as JSON — extract figures
   (`image_extractor.py`), attaching `owner_citation` via strip-and-match against the full
   citation set collected in step 1. Skipped/failed fetches are logged to stderr, not fatal.
3. Write `output/web_toc.json` (`json_writer.py`).

Progress is printed to stderr per section fetched (there are ~100), since a full run makes
~100+ HTTP requests and can take a couple of minutes — mirroring `build_mo_toc.py`'s
`print(..., file=sys.stderr)` progress convention.

Images are **not** downloaded or thumbnailed locally — the viewer hotlinks
`https://dev.buildingcode.gov.bc.ca/{src}.jpg` directly at render time. They're already
public, static, web-optimized files served by the official site, so mirroring them would only
add storage and a staleness risk for no benefit. (If offline use ever matters, this is the one
place a later change would slot in — `json_writer.py`'s output shape doesn't need to change,
just an extra download step before it.)

### Web viewer changes (additive only)

- **`src/mo_toc/web/api.py`**: `create_app` gains an optional `web_toc_json_path: str | None`
  parameter. If the file exists, its payload is loaded eagerly (same pattern as the existing
  `toc_json_path` payload) and a new `GET /api/web-toc` route returns it. If the path is `None`
  or the file is missing, the route still exists but returns
  `HTTPException(503, "Run src/build_web_toc.py first")` — so a fresh checkout that hasn't run
  the new build script yet still serves the three existing tabs normally; only the new tab
  shows a "not built yet" state.
- **`src/serve_mo_toc.py`**: `_get_app()` additionally checks for `output/web_toc.json` and
  passes its path (or `None`) through to `create_app` — no change to the existing
  `TOC_JSON`/`PDF_PATH`/`THUMBNAILS_DIR` handling or its "missing file" error for the PDF data.
- **`index.html`**: a 4th tab button, `id="tab-web-images"`, labeled "BC Code (Web) — Table of
  Images", its own content div (checkbox-free — there's no bbox-based declutter concept here),
  and a hidden detail panel (`id="web-image-detail"`) for the clicked image's alt text,
  citation, and link-out.
- **`viewer.js`**: `loadWebToc()` fetches `/api/web-toc` once; a pruned-tree renderer
  (`renderWebTreeNode`, following the exact same "only show branches with images, attach
  images at their owning node" pattern `renderImageTreeNode`/`attachImagesToOwners` already
  use for the PDF's Table of Images) builds the tab. Clicking an image populates the detail
  panel instead of calling `goToLocation` (there's no page/bbox to scroll to) and shows a
  "View on official site ↗" anchor pointing at
  `https://dev.buildingcode.gov.bc.ca{node.path}?version=2024&date=2024-03-08` with
  `target="_blank"`. Script cache-bust query bumps to `?v=4`.

## Testing

Same TDD discipline and file layout convention as `mo_toc/`'s tests:

- `tests/test_web_toc_tree_builder.py` — pure, feeds a small hand-built navigation-tree dict.
- `tests/test_web_toc_content_url.py` — the dispatch table, one case per node type + the
  `index`/`conversions` skip.
- `tests/test_web_toc_image_extractor.py` — figure extraction + strip-and-match owner
  assignment, including a figure nested inside a table cell (mirrors the real
  `part-9/section-23.json` shape) and a figure with no matching ancestor (dropped, logged).
- `tests/test_build_web_toc.py` — orchestration wiring, `WebSource` faked (no real HTTP).
- `tests/test_web_toc_api.py` — the new `/api/web-toc` route, including the "file missing →
  503" path, using `create_app` directly (same pattern `test_api.py` already uses).
- One `slow`-marked integration test that fetches one real, small, known-stable section (e.g.
  `nbc-diva/part-1/section-1.json`, ~1.7 KB per an earlier check, no figures) from the live
  site, mirroring the existing real-1685-page-PDF `slow` test's role: a real-network smoke
  test, skipped by default.

`WebSource` is a small `Protocol` (`fetch_navigation_tree() -> dict`,
`fetch_content(url: str) -> dict | None`) so every other test fakes it — no real HTTP calls in
the default `pytest -q` run, consistent with `PyMuPdfSource` being fakeable in the existing
suite.

## Out of scope

- `index` and `conversions` node types (no working content URL found; low value — no figures
  expected).
- Local caching/thumbnailing of images (hotlinked instead, see above).
- Reproducing the live site's own page rendering in-app (detail panel + link-out instead).
- Detecting/handling future changes to the site's URL scheme beyond what's verified here —
  the `{` -based validity check means a scheme change degrades to "fewer images extracted,
  logged," not a crash, but re-verifying the scheme is a follow-up if the live site changes.

## Known oddity, not a blocker

`navigation-tree.json`'s own top-level `"version"` field reads `"2020"` even though it's
served from `/data/2024/...` and the site's URL takes `?version=2024`. Not investigated
further — doesn't affect this design, since the URL derivation rules above were all verified
directly against live responses, not inferred from that field.
