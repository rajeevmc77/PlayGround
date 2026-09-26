# Design: MO Package structural index + interactive TOC/Image viewer

Status: approved by user 2026-09-20. Next step: implementation plan via writing-plans skill.

## 1. Purpose

Replace the ad hoc `bcbc_mo_index.py` / `extract_figures.py` scripts (archived, not reused)
with a freshly designed, Clean-Architecture, TDD-built system that:

1. Parses `data/MO Package BCBC MRK signed.pdf` (1685 pages) into a full hierarchical
   structural index down to Subclause level, with page number **and** precise bounding-box
   coordinates for every node (so a viewer can jump to the exact spot, not just the page).
2. Indexes every embedded raster image in the document (page, bbox, pixel size, perceptual
   hash, thumbnail) — no size/caption filtering at the data layer.
3. Serves both as JSON + Markdown (as before), and through a new interactive web viewer:
   a collapsible TOC/Images tree next to a live-rendered page view that scrolls to and
   highlights the exact clicked location.

Out of scope: `bcbc_2024.pdf` indexing (that code is archived, not rebuilt); any change to
`app.py`'s OAuth/Directory tool (unrelated concern, left untouched).

## 2. Document schema (verified against the real PDF, not assumed from a generic diagram)

Checked directly with PyMuPDF text/font extraction before finalizing this schema:

- **No literal "Preface", "Index", or "Conversion Factors" sections exist in this PDF.**
  Those belong to the *published BCBC book*; this document is a Ministerial Order merge
  package. Every "Index"/"Preface" text hit found by full-document search is a body-text
  word inside unrelated sentences, not a heading.
- **Pages 1–5**: front matter — two Ministerial Order signature/approval pages, before
  "Division A" starts on page 6 (confirmed: first `Arial-Black` heading line in the whole
  document is "Division A" on page 6). The archived code silently dropped this content
  (no heading was open yet, so lines were discarded rather than attributed anywhere).
- **Pages 1675–1676**: a second Ministerial Order (adopting the BC *Fire Code*), same
  front-matter shape as pages 1–5, inserted after Division C's own content ends.
- **Pages 1677–1685**: a "SCHEDULE" section (the Fire Code Order's own amendment schedule),
  headed by a standalone line `SCHEDULE` in `Cambria-Bold`, with its own numbered items
  (e.g. "1.1.1.1. Application of this Code") rendered in `Calibri-Bold`/`Calibri-BoldItalic`
  — never `Arial-Black`. The archived code's heading detector requires `"Black" in font`
  (matching only `Arial-Black`), so none of this was recognized as headings; it was
  silently absorbed as body text of whatever Article/Note was still open from Division C.
  This is a genuine, previously undocumented bug in the archived implementation.
- Confirmed still true from the archived code's own analysis: no literal "Volume" heading
  anywhere (synthetic root, spans the whole document); the
  `Division → Part → Section → Subsection → Article → Sentence → Clause → Subclause` chain;
  `Part → NotesContainer ("Notes to Part N") → Note` as a sibling chain under Part;
  the parallel Appendix numbering `Appendix → AppendixPart ("Section D-1") →
  AppendixSection ("D-1.1.") → AppendixArticle ("D-1.1.1.") → Sentence → Clause → Subclause`,
  used by Appendix C and D, inserted after Division B's Part 10 and before Division C.

### Target tree (Volume's direct children, in document order)

```
Volume (synthetic root, whole document)
  FrontMatter            (pp. 1-5: Ministerial Order + Approval Form)
  Division A / B / C     (full existing chain, incl. NotesContainer -> Note)
  Appendix C / D         (AppendixPart -> AppendixSection -> AppendixArticle chain)
  BackMatter             (pp. 1675-1685: 2nd Ministerial Order + its SCHEDULE)
```

`FrontMatter` and `BackMatter` are new rank-1 node types (siblings of Division/Appendix).
Their own internal structure is NOT parsed into Sentence/Clause/Subclause — they're captured
as single nodes spanning their page range, since they're administrative/legal text, not code
provisions the user's numbering scheme applies to. (If deeper structure inside them is ever
wanted, that's a future, separately-scoped enhancement — YAGNI for now.)

## 3. Data model

```python
# domain/models.py — pure dataclasses, no PyMuPDF/HTTP/file-I/O imports

@dataclass
class BBox:
    x0: float; y0: float; x1: float; y1: float   # PDF points, top-left origin

@dataclass
class Node:
    type: str            # Volume|FrontMatter|Division|Part|NotesContainer|Section|
                          # Subsection|Article|Sentence|Clause|Subclause|Note|
                          # Appendix|AppendixPart|AppendixSection|AppendixArticle|
                          # TableGroup|BackMatter
    identifier: str
    citation: str
    title: str
    page: int             # 1-based
    end_page: int
    bbox: BBox             # location of the heading's own first line
    children: list["Node"]

@dataclass
class Caption:                # Table / Figure captions (flat list, not tree nodes)
    kind: str                 # "Table" | "Figure"
    identifier: str
    title: str
    page: int
    bbox: BBox
    owner_citation: str
    forming_part_of: str | None
    continuation: bool

@dataclass
class ImageAsset:
    page: int
    bbox: BBox
    width: int; height: int   # pixel dimensions
    phash: str | None
    thumbnail_path: str        # relative path under output/
```

All existing citation/numbering logic from the archived code's *domain knowledge*
(Part.Section.Subsection.Article numbering, Sentence `(1)`/Clause `(a)`/Subclause `(i)`
bracket convention, roman-numeral ambiguity resolution) carries over as freshly written
logic in `parsing/marker_rules.py` — this is generic BCBC numbering-convention knowledge,
not code reused from the archive.

## 4. Architecture

```
src/mo_toc/
  domain/models.py         # pure dataclasses (above)
  parsing/pdf_source.py     # PdfSource interface (abstract: iter_page_lines, iter_page_images)
                            #   + PyMuPdfSource adapter — the seam that lets heading/marker/
                            #   tree logic be unit-tested with fake page data, no real PDF
  parsing/heading_rules.py  # pure: (text, font) -> heading type | None, incl. new
                            #   FrontMatter/BackMatter marker patterns
  parsing/marker_rules.py   # pure: Sentence/Clause/Subclause token classification
  parsing/tree_builder.py   # orchestrates PdfSource + heading_rules + marker_rules
                            #   -> (Volume root Node, flat Caption list, flat ImageAsset list)
  output/json_writer.py
  output/markdown_writer.py
  web/api.py                 # standalone FastAPI app (separate from app.py — no OAuth,
                              #   unrelated concern per CLAUDE.md's "two independent tools")
  web/static/index.html
  web/static/viewer.js
  web/static/style.css
src/build_mo_toc.py           # CLI: parse PDF -> write output/mo_toc.json + output/mo_toc.md
src/serve_mo_toc.py           # CLI: launch the viewer (uvicorn)
tests/
  test_heading_rules.py
  test_marker_rules.py
  test_tree_builder.py        # uses a FakePdfSource fixture
  test_api.py                 # FastAPI TestClient against fixture data
  test_integration_real_pdf.py # slow, spot-checks only, marked so it's skippable
```

## 5. Heading detection additions (new marker patterns)

```python
RE_FRONT_MATTER_START = re.compile(r"^PROVINCE OF BRITISH COLUMBIA$")   # Arial-BoldMT
RE_SCHEDULE = re.compile(r"^SCHEDULE$")                                  # Cambria-Bold
```

`FrontMatter` opens at document start (page 0) unconditionally — it's whatever precedes the
first real Division/Appendix heading. `BackMatter` opens when a rank-1 heading pattern
(`RE_FRONT_MATTER_START` recurring, or `RE_SCHEDULE`) is seen *after* at least one Division
has already closed — i.e., after the main Division/Appendix chain, not before. Implementation
detail (exact page-range boundaries between the two Ministerial Orders vs. the true end of
Division C content) is confirmed by direct inspection during implementation, per this
project's established practice of validating against page/data subsets before a full run.

## 6. Interactive viewer

**Approach (recommended, chosen):** custom lightweight viewer using pdf.js's core rendering
library directly (not the full prebuilt viewer app), vanilla JS, no build step/bundler.

- Left sidebar: two tabs, "Table of Contents" (lazy-expanding tree — only builds a node's
  child DOM elements when the user expands it, so tens of thousands of Sentence/Clause/
  Subclause nodes never all hit the DOM at once) and "Images" (flat list, thumbnails).
- Main panel: pdf.js renders the current page to a `<canvas>`. Clicking any tree/image
  entry: (a) loads that page if not already shown, (b) scrolls the container so the node's
  bbox sits near the top of the viewport, (c) draws a temporary highlight rectangle over
  the exact bbox (an absolutely-positioned overlay `<div>` scaled via pdf.js's
  `viewport.convertToViewportRectangle()`) that fades out after ~2s.
- Prev/Next page controls, current-page indicator.
- Images tab defaults to hiding images under 40pt in either dimension (a client-side
  toggle, since the underlying data captures every embedded image per the user's choice,
  but a page's worth of tiny repeated icons/logos would otherwise clutter the list); one
  click shows everything.

**Alternative considered and rejected:** embedding the full prebuilt PDF.js viewer
(`viewer.html`) in an iframe, driven via `scrollPageIntoView`. Gets pan/zoom/search for
free but is a multi-MB bundle, harder to integrate with a custom tree sidebar via
cross-frame messaging, and is overkill for a single-user local tool.

**Alternative rejected:** pre-rendering all 1685 pages to static images at build time —
heavy storage, worse UX (no selectable text layer), no benefit over on-demand rendering.

**Coordinates:** PyMuPDF bboxes are already top-left-origin PDF points — exactly what
pdf.js's `viewport.convertToViewportRectangle()` consumes directly. No coordinate-system
translation needed.

**Update (2026-09-26):** the separate "Table of Contents - pdf" and "Table of Contents - web"
tabs are gone. The viewer now has two tabs:
- **"Table of Contents - Both"**, the default. The PDF tree drives the PDF page and the
  matching saved web page side by side, joined by `unified_number`.
- **"Compare"**, for PDF vs web images.

The Both tab's filters work in two ways:
- Figures, Equations / Formula and Images choose which image rows attach to the tree.
- Tables and Text show or hide rows of the tree itself. Text covers Sentence, Clause,
  Subclause and Note. A hidden Table takes its Rows and Cells with it.

Headings (Volume … Article, and the Appendix chain) always stay. A hidden text row's still-shown
contents move up to its parent, e.g. a Table out of its Sentence. So do the images of any
hidden row: they attach to the nearest row still shown. See `isShownInBoth`,
`visibleBothChildren` and `bothHostCitations` in `web/static/both_view.mjs`.

## 7. Web API (`web/api.py`)

- `GET /api/toc` — full JSON tree (Volume root with nested children).
- `GET /api/images?include_all=false` — image list; `include_all=true` skips the 40pt
  declutter floor (data itself is never filtered; this is a query-level view, not a
  storage-level one).
- `GET /pdf` — streams `data/MO Package BCBC MRK signed.pdf` (supports HTTP Range requests,
  needed by pdf.js's streaming fetch).
- `GET /api/image/{index}/thumbnail` — serves a pre-extracted thumbnail PNG.

No auth — this is local reference data, not the OAuth-gated Directory/Drive tool.

## 8. Testing strategy (TDD per CLAUDE.md)

- **Unit (fast, no PDF I/O):** `heading_rules`/`marker_rules` against synthetic
  `(text, font)` inputs, covering every documented edge case (Arial-Black gate, roman
  numeral ambiguity, FrontMatter/BackMatter markers). `tree_builder` against a
  `FakePdfSource` fixture covering full nesting depth, a Note, an Appendix, a Table/Figure
  caption, front matter, back matter — assert exact resulting tree shape/citations/pages.
- **One slow integration test** against the real PDF, asserting only known spot-checks
  (Division A starts page 6, Appendix C/D sit between Division B and C, BackMatter starts
  page 1677) — marked `@pytest.mark.slow` so `pytest -q` can skip it by default, consistent
  with this project's "test a small sample first" working note for the full 1685-page PDF.
- **Web layer:** FastAPI `TestClient` tests against fixture data, not the real multi-MB tree.
- Adds `pyproject.toml` (ruff + pytest config, `markers = ["slow"]`) since this is new work
  the Definition-of-Done checklist (ruff, radon ≤B, vulture, pytest --cov) now applies to.

## 9. Archive step

Move (not delete) into `Archive DO NOT Refer/` at the project root:
`src/bcbc_mo_index.py`, `src/bcbc2024_index.py`, `src/extract_figures.py`,
`src/extract_figures_2024.py`, `ai_docs/bcbc_mo_index_spec.md`, and their generated
`output/` artifacts (`bcbc_mo_index.json`/`.md`, `bcbc_mo_index_figures.json`/`.md`/
`figures/`, `bcbc2024_index.json`/`.md`, `bcbc2024_index_figures.json`/`.md`/
`figures_2024/`). `CLAUDE.md` is updated to describe the new architecture and drop
references to the retired scripts.

## 10. Deliverables

- `output/mo_toc.json` — full-fidelity tree (Volume → ... → Subclause), flat Caption list,
  flat ImageAsset list.
- `output/mo_toc.md` — human-readable index, same shape/conventions as the archived
  Markdown report (summary counts, full hierarchy table with page/length, Table/Figure
  index tables), regenerated by the new pipeline.
- `output/thumbnails/` — one PNG per `ImageAsset`.
- Running `python src/serve_mo_toc.py` launches the interactive viewer locally.
