# Equation/formula image extraction — design spec

Date: 2026-10-12

## Problem

Image extraction treats equations as an afterthought on both sides of the
comparison pipeline:

- **PDF side** (`src/mo_toc/`): a vector-drawn equation (fraction bar,
  summation, stacked sub/superscripts) is captured by the same generic
  diagram-clustering heuristic used for figures. That heuristic merges
  drawing-path rects only when they're within `MERGE_MARGIN = 5pt`
  (`src/mo_toc/parsing/vector_cluster.py:15`) — a multi-line/stacked
  formula whose lines are spaced wider than that gets clipped into
  separate, incomplete pieces instead of one complete equation image.
- **Web side** (`src/web_toc/`, `src/build_web_pages.py`): an equation is
  captured by screenshotting MathJax's own *rendered* glyph box on the
  live saved page (`src/web_toc/parsing/equation_script.py`). The site's
  content JSON actually carries the equation's real `latex`/`mathml`
  source per node, but nothing in `web_toc` reads those fields — they're
  discarded when the tree is built.

A separate, unintegrated module, `src/equation_export/`, already fetches
the site's real LaTeX/MathML (via a different endpoint, `equation-map.json`)
and renders standalone PNGs. It was never wired into `web_toc`,
`build_web_pages.py`, or `src/comparison/image_pairing.py` — no
`unified_number`, no tree placement, no participation in the viewer or the
pass/fail comparison.

## Verified facts this design relies on

- The content JSON `build_web_pages.py` already caches per page (under
  `output/web_source/content/*.json`) carries `latex`, `mathml`, and
  `plainText` fields directly on each equation node, identical to what
  `equation-map.json` would give — confirmed by diffing a cached node
  (`es008333q1` in `nbc.divBV2.part9.sect15.json`) against a live fetch of
  `equation-map.json`, and then by comparing all 129 non-empty equation
  node ids across all 70+ cached content-JSON files: 100% match, `latex`
  byte-identical. **This means `equation-map.json` is unnecessary** — no
  new network dependency is needed; `web_toc`'s content-JSON parsing just
  needs to stop discarding fields it already has.
- `src/web_toc/parsing/equation_script.py:42` derives each equation
  occurrence's key as `<owner id>.<data-node-id>[-n]`, where
  `data-node-id` **is** the content-JSON node's own `id` — the same id
  that carries `latex`/`mathml`. No separate id-correlation step is
  needed.
- `src/equation_export/rendering/mathjax_renderer.py`'s `MathJaxRenderer`
  already does real MathJax headless-browser rendering (loads the same
  MathJax bundle the live site uses, typesets a MathML string into a
  scratch page, screenshots the whole rendered element — not a cropped
  in-page glyph box). It is reused by this design as the sole renderer;
  `equation_export`'s matplotlib-mathtext path (`latex_renderer.py`) and
  its LaTeX-normalization workarounds (`equation_source.py`'s
  `_GLUED_COMMAND_RE`/`_TEXT_COMMAND_RE`/`_PUA_PAREN_MAP`) are dropped —
  those exist only to work around matplotlib mathtext's limitations,
  which don't apply when MathJax does the rendering.
- `src/equation_export/parsing/equation_source.py` (the `equation-map.json`
  HTTP fetch) is now fully redundant and is retired, along with the
  standalone `src/export_equations.py` entry point.
- `src/comparison/image_pairing.py:80`'s `image_counterparts()` already
  pairs PDF-to-web images by `unified_number`; it needs no change — an
  equation node just needs to reach it with a real `unified_number` and
  image path like any figure does today.

## Scope

1. Web side: read `latex`/`mathml` from the content JSON, render via
   MathJax (not a live-page screenshot), wire the result to
   `unified_number` the same way figures already are, retire the
   now-redundant `equation_export` fetch/matplotlib path.
2. PDF side: fix the clipping risk for stacked/multi-line vector-drawn
   equations so the full formula is captured as one image.
3. No changes to `src/comparison/image_pairing.py` or the viewer — both
   already key off `unified_number`/the existing `WebImage`/image-index
   shape.

## Design — web side

### What changes in the per-page render/swap step

`build_web_pages.py`'s existing per-page headless-Chromium pass already
renders each saved page (with MathJax loaded and typeset) before
swapping `.equation-block`s to static `<img>` tags and measuring layout.
That swap point is where the content changes:

- **Geometry (unchanged):** `MARK_EQUATIONS_JS` still tags each
  `.equation-block[data-equation-key]` with its owner/key, and the
  swap step still reads the live-rendered `mjx-math` glyph box's
  `getBoundingClientRect()` to size and position the replacement `<img>`
  — this is what keeps the swapped-in image aligned with surrounding
  text exactly as today, and is independent of where the image's pixel
  content comes from.
- **Pixel content (changed):** instead of screenshotting that in-page
  glyph box, look up the node's cached `mathml` (by `data-node-id`, i.e.
  the content-JSON node id) and render it via one shared
  `MathJaxRenderer` instance (opened once per `build_web_pages.py` run,
  closed at the end — matching the class's existing documented lifetime
  contract) into a PNG saved under the same two locations the current
  screenshot uses (`output/web_images/equations/`,
  `output/web_pages/assets/equations/`), named by the occurrence key.
  Falls back to rendering normalized `latex` only for the rare node
  missing `mathml`.
- Rendering the full MathJax-typeset element (not a cropped glyph box
  read off the live page) is what gives a complete, unclipped image even
  for a formula whose on-page layout might otherwise crop awkwardly —
  this is the web-side half of "download it in its complete form."
- This still happens entirely inside the main (network-touching) run,
  before the page is saved for later offline measurement — so
  `--measure-only` keeps working exactly as before (it never touches
  MathJax or the network; by the time it runs, equation markup is
  already gone from the saved page).

### What changes in content-JSON parsing

Wherever `web_toc`'s parsing of the cached content JSON currently builds
each node (structure/numbering pass), it needs to also keep the node's
`latex`/`mathml` fields available by node id, so the per-page render step
above can look them up. This is additive — existing fields/behavior are
unchanged.

### Unified key wiring

No new wiring is needed beyond what exists: `WebImage.id` stays the
occurrence key (`layout_join.py:204`), and whatever downstream step
assigns `unified_number` to images today keeps doing so unchanged — the
only thing that changed is where the referenced PNG's pixel content came
from.

### Retirement

- `src/equation_export/parsing/equation_source.py` (HTTP fetch) and
  `src/equation_export/rendering/latex_renderer.py` (matplotlib mathtext)
  are deleted, along with `src/export_equations.py` and their
  `equation-map.json`-fetching tests.
  `src/equation_export/rendering/mathjax_renderer.py` and
  `src/equation_export/output/png_exporter.py`'s rendering logic are kept
  (moved into `web_toc`, or imported from `equation_export` if that
  module is kept as a thin home for the renderer — implementation detail
  for the plan to decide) since they're now load-bearing.

## Design — PDF side

Add a second clustering pass, scoped **only** to clusters already
classified as equation-shaped (`is_equation_shaped()`,
`src/mo_toc/domain/image_classification.py:35`), that merges
vertically-stacked pieces using a wider gap tolerance than the general
`MERGE_MARGIN = 5pt` diagram-merge margin:

- The general vector-diagram clustering (`cluster_drawing_rects`,
  `vector_cluster.py`) runs unchanged first — this is what keeps
  separate diagrams from merging into each other.
- A new function merges equation-shaped clusters that are vertically
  stacked (gap between them within a tolerance derived from local body
  text line-height, not a fixed enlarged constant — so it doesn't start
  swallowing unrelated nearby elements) and horizontally overlapping
  (same formula column: numerator over denominator, base over
  subscript/superscript stack, etc.).
- Table-grid exclusion (already applied before equation classification)
  continues to run first, so this pass never operates on table rule
  lines.
- The merged cluster is rasterized the same way
  (`PdfSource.page_drawing_rects`/`get_pixmap` at 3x zoom,
  `pdf_source.py:184-203`) — only the clustering changes, not the
  rendering.

### Amendment (2026-10-13): PDF-side design superseded

This section's design is superseded. PDF equations are identified by the
tagged PDF's structure-tree `/Alt (EQUATION)` tag
(`PdfSource.page_image_alts`); the shape heuristic only decides for
untagged rasters, and an equation-shaped vector crop is left unkeyed
(neither Eq nor Fig). The stacked-fragment merge described above was
built (`merge_equation_fragments`), measured a no-op on the real PDF (no
formula in it is vector-drawn), and - since under the unkeyed-vector rule
its output could never be keyed Eq and could only remove figures from
numbering - removed. The main plan's Tasks 1-2 and this spec's
stacked-merge tests are historical. See the plan addendum
`docs/superpowers/plans/2026-10-12-equation-image-extraction-addendum.md`.

## Testing

Per `CLAUDE.md`'s TDD workflow:

- New unit tests for the stacked-equation-cluster merge (synthetic
  drawing-rect fixtures: a 2-line fraction with a gap >5pt but within
  line-height tolerance merges into one cluster; two genuinely separate
  diagrams don't merge).
- New unit tests for the MathJax-render wiring: given a content-JSON node
  with `mathml`, the right PNG is produced and keyed by the right
  occurrence key; a node missing `mathml` falls back to `latex`; a node
  with neither fails gracefully and is reported, not silently dropped.
- Migrate `test_equation_export_mathjax_renderer.py` and
  `test_equation_export_png_exporter.py` (actually-useful renderer
  correctness) to wherever the renderer ends up living.
- Retire `test_equation_export_equation_source.py`,
  `test_equation_export_latex_renderer.py`, `test_export_equations.py`,
  and `test_equation_export_domain_models.py` pieces tied only to the
  retired fetch/matplotlib path.
- Update `test_web_toc_equation_capture.py` /
  `test_web_toc_layout_join.py` for the new render source.
- No changes expected to `test_comparison_image_pairing.py` — verify the
  existing tests still pass unchanged as the acceptance check that
  `unified_number` pairing needed no modification.

## Out of scope

- Changing `src/comparison/equation_text.py`'s OCR-based PDF-vs-web text
  comparison for equations — unrelated to image sourcing.
- Any change to `src/comparison/image_pairing.py`'s Fig/Eq relabeling
  fallback — kept as-is, it compensates for genuine content differences,
  not implementation artifacts.
