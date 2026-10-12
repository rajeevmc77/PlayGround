# Equation/Formula Image Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every equation/formula image complete on both sides of the comparison pipeline: fix PDF-side clipping of stacked/multi-line vector-drawn equations, and replace the web side's screenshot-of-rendered-MathJax approach with rendering each equation from the site's own cached `latex`/`mathml` via MathJax.

**Architecture:** On the PDF side, add a second vector-clustering pass that merges stacked equation fragments the general diagram-clustering margin misses, gated by "does the merged result read as one equation" so it can never swallow a real diagram. On the web side, keep the existing mark/swap DOM mechanics (which already give correct sizing/positioning) but source each equation's pixel content from a shared, async, headless-browser MathJax renderer fed by the equation's own `latex`/`mathml` (read from the content JSON `build_web_pages.py` already caches), keyed exactly as today so `unified_number`/`image_pairing.py`/the viewer need no changes.

**Tech Stack:** Python 3.10+, PyMuPDF (`fitz`, via `PdfSource`), Playwright (async API), pytest.

**Spec:** [docs/superpowers/specs/2026-10-12-equation-image-extraction-design.md](../specs/2026-10-12-equation-image-extraction-design.md)

## Global Constraints

- Functions ≤20 executable lines, cyclomatic complexity ≤6, nesting ≤2 levels (CLAUDE.md Code standards).
- TDD throughout: failing test → minimal code → refactor. Never weaken or delete an existing test to make a build pass.
- Clean Architecture: domain/business logic (shape classification, clustering, equation-source parsing) stays free of HTTP/OAuth/file-I/O/PDF-library specifics; inject dependencies through small interfaces rather than instantiating concrete classes inline — except where following an established in-file pattern (see Task 8 note on `EquationRenderer`).
- Every new/changed file here falls under CLAUDE.md's Definition of Done scope (`src/mo_toc/`, `src/web_toc/`, `src/build_web_pages.py`, `tests/`) — run `ruff check --fix . && ruff format .`, `radon cc -s -n B .`, `vulture .`, `pytest --cov=.` before calling any task done, and again at the end (Task 10).
- Each task is its own commit; follow the repo's git-worktree-and-PR workflow (CLAUDE.md "New code or enhancements") at execution time, not as a plan task.

## Review Focus

- An equation node whose `mathml` is missing must still render, via the LaTeX fallback path — if this silently fails, every equation lacking `mathml` would quietly vanish from the web side. (Task 7)
- An equation occurrence whose `node_id` has no matching cached content-JSON source (renamed/missing node) must be skipped with a clear message, without crashing the run or losing the *other* equations on the same page. (Task 8)
- Two equation occurrences (different per-page keys) that share the same underlying `node_id` — the site's documented id-reuse — must each resolve to the correct, non-cross-contaminated rendered content. (Task 8)
- A real diagram sitting close enough to an equation-shaped crop to fall within the new wider stacked-equation gap tolerance must never be absorbed into it — the whole point of gating by "does the merge read as one equation" is to prevent exactly this kind of false merge corrupting a real figure. (Task 1)
- The site's own double-escaped-backslash LaTeX quirk (confirmed in `equation_export`'s existing code) must still be normalized before the LaTeX fallback is handed to MathJax, or a common formula shape fails to typeset. (Task 7)

---

## Task 1: PDF — merge stacked/multi-line vector equation fragments

**Files:**
- Modify: `src/mo_toc/parsing/vector_cluster.py`
- Test: `tests/test_vector_cluster.py`

**Interfaces:**
- Produces: `merge_equation_fragments(clusters: list[BBox]) -> list[BBox]` — takes the output of `cluster_drawing_rects`, returns clusters with stacked equation fragments combined. Consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vector_cluster.py`:

```python
from mo_toc.parsing.vector_cluster import merge_equation_fragments


def test_stacked_fraction_pieces_merge_when_gap_exceeds_general_margin():
    numerator = (0, 0, 60, 8)
    denominator = (0, 20, 60, 28)  # 12pt gap: > MERGE_MARGIN(5), within STACK_GAP_LIMIT
    result = merge_equation_fragments([numerator, denominator])
    assert result == [(0, 0, 60, 28)]


def test_two_separate_diagrams_stay_separate():
    top = (0, 0, 50, 50)
    bottom = (0, 60, 50, 110)  # 10pt gap, but the union is too tall to be an equation
    result = merge_equation_fragments([top, bottom])
    assert sorted(result) == sorted([top, bottom])


def test_stacked_but_not_horizontally_overlapping_stays_separate():
    left = (0, 0, 40, 8)
    right = (100, 20, 140, 28)
    result = merge_equation_fragments([left, right])
    assert sorted(result) == sorted([left, right])


def test_gap_beyond_the_tallest_known_equation_stays_separate():
    top = (0, 0, 60, 8)
    bottom = (0, 100, 60, 108)  # 92pt gap, well past STACK_GAP_LIMIT
    result = merge_equation_fragments([top, bottom])
    assert sorted(result) == sorted([top, bottom])


def test_a_rule_line_between_two_formula_fragments_is_not_absorbed():
    numerator = (0, 0, 60, 8)
    rule_line = (0, 14, 60, 14.5)  # a thin table/underline rule sitting between them
    denominator = (0, 20, 60, 28)
    result = merge_equation_fragments([numerator, rule_line, denominator])
    # The numerator/denominator may still combine (their own union reads as an
    # equation), but the thin rule line must never be pulled in as a third
    # piece, and must never end up merged on its own into something that
    # reads as an equation either.
    assert rule_line not in result
    tall_enough = [c for c in result if c[3] - c[1] > 9]
    assert len(tall_enough) == 1


def test_empty_and_single_cluster_are_unchanged():
    assert merge_equation_fragments([]) == []
    assert merge_equation_fragments([(0, 0, 60, 8)]) == [(0, 0, 60, 8)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vector_cluster.py -v`
Expected: FAIL with `ImportError: cannot import name 'merge_equation_fragments'`

- [ ] **Step 3: Implement**

In `src/mo_toc/parsing/vector_cluster.py`, add the import and the new code (after the existing `MIN_CLUSTER_AREA` constant, before `_expand`):

```python
from mo_toc.domain.image_classification import is_equation_shaped

# pt; a stacked formula's lines (fraction bar, summation limits, sub/
# superscripts) can sit farther apart than any diagram's own strokes ever
# do - reuses image_classification's own ceiling for how tall one equation
# can be, so this pass can never bridge a gap wider than an equation itself.
STACK_GAP_LIMIT = 70.0
# Fraction of the narrower cluster's width that must overlap horizontally
# for two clusters to plausibly be the same formula's stacked lines.
MIN_STACK_OVERLAP_FRACTION = 0.5
```

Add after `_area`:

```python
def _x_overlap(a: BBox, b: BBox) -> float:
    ax0, _, ax1, _ = a
    bx0, _, bx1, _ = b
    return max(0.0, min(ax1, bx1) - max(ax0, bx0))


def _vertical_gap(a: BBox, b: BBox) -> float:
    _, ay0, _, ay1 = a
    _, by0, _, by1 = b
    return max(ay0, by0) - min(ay1, by1)


def _is_stacked_pair(a: BBox, b: BBox) -> bool:
    gap = _vertical_gap(a, b)
    if not (0 <= gap <= STACK_GAP_LIMIT):
        return False
    narrower_width = min(a[2] - a[0], b[2] - b[0])
    return _x_overlap(a, b) >= MIN_STACK_OVERLAP_FRACTION * narrower_width


def _reads_as_equation(rect: BBox) -> bool:
    x0, y0, x1, y1 = rect
    return is_equation_shaped(x1 - x0, y1 - y0)


def _find_stackable_pair(rects: list[BBox]) -> tuple[int, int] | None:
    for i, j in combinations(range(len(rects)), 2):
        if _is_stacked_pair(rects[i], rects[j]) and _reads_as_equation(_union(rects[i], rects[j])):
            return i, j
    return None


def merge_equation_fragments(clusters: list[BBox]) -> list[BBox]:
    """Merges pairs of clusters stacked closely enough and overlapping
    enough horizontally to plausibly be one formula's separate lines - but
    only when the MERGED result itself reads as a complete equation
    (is_equation_shaped), so two genuinely separate diagrams - which never
    combine into something wide-and-short - are left untouched even if one
    sits just above the other."""
    clusters = list(clusters)
    pair = _find_stackable_pair(clusters)
    while pair is not None:
        i, j = pair
        clusters[i] = _union(clusters[i], clusters[j])
        del clusters[j]
        pair = _find_stackable_pair(clusters)
    return clusters
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_vector_cluster.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/vector_cluster.py tests/test_vector_cluster.py
git commit -m "feat(mo_toc): merge stacked vector equation fragments across a wider gap"
```

---

## Task 2: PDF — wire the fragment merge into vector image extraction

**Files:**
- Modify: `src/mo_toc/parsing/image_extractor.py:98-113` (`vector_images_on_page`)
- Test: `tests/test_image_extractor.py`

**Interfaces:**
- Consumes: `merge_equation_fragments` from Task 1 (`mo_toc.parsing.vector_cluster`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_image_extractor.py`:

```python
def test_vector_images_on_page_merges_stacked_equation_fragments():
    numerator = (0, 0, 60, 8)
    denominator = (0, 20, 60, 28)  # 12pt gap - would stay split without the merge pass
    rendered = []
    source = _fake_source(rendered)

    result = vector_images_on_page(source, 0, raster_bboxes=[], drawing_rects=[numerator, denominator])

    assert len(result) == 1
    assert rendered == [(0, 0, 60, 28)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_image_extractor.py -v -k merges_stacked`
Expected: FAIL — two separate images are rendered instead of one (`rendered` has 2 entries)

- [ ] **Step 3: Implement**

In `src/mo_toc/parsing/image_extractor.py`, add the import:

```python
from mo_toc.parsing.vector_cluster import (
    cluster_drawing_rects,
    exclude_overlapping_rects,
    merge_equation_fragments,
)
```

Update `vector_images_on_page` (the first two lines of its body):

```python
    rects = drawing_rects if drawing_rects is not None else source.page_drawing_rects(page_index)
    clusters = cluster_drawing_rects(rects)
    clusters = merge_equation_fragments(clusters)
    clusters = exclude_overlapping_rects(clusters, list(raster_bboxes) + list(table_bboxes))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_image_extractor.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/image_extractor.py tests/test_image_extractor.py
git commit -m "feat(mo_toc): capture stacked vector equations as one complete image"
```

---

## Task 3: Web — domain models for equation sources and marked equations

**Files:**
- Modify: `src/web_toc/domain/models.py`
- Test: `tests/test_web_toc_models.py` (doesn't exist yet — create it)

**Interfaces:**
- Produces: `EquationSource(latex: str, mathml: str | None = None)`, `MarkedEquation(key: str, node_id: str)`, and `EquationCapture(html: str, marked: list[MarkedEquation])` (replacing its old `images: dict[str, bytes]` field). Consumed by Tasks 4, 5, 7, 8.

- [ ] **Step 1: Write the failing test**

Create (or append to) `tests/test_web_toc_models.py`:

```python
from web_toc.domain.models import EquationCapture, EquationSource, MarkedEquation


def test_equation_source_defaults_mathml_to_none():
    source = EquationSource(latex="x^2")
    assert source.mathml is None


def test_marked_equation_holds_key_and_node_id():
    marked = MarkedEquation(key="p3.es1", node_id="es1")
    assert (marked.key, marked.node_id) == ("p3.es1", "es1")


def test_equation_capture_holds_html_and_marked_equations():
    capture = EquationCapture(html="<html></html>", marked=[MarkedEquation("p3.es1", "es1")])
    assert capture.marked[0].key == "p3.es1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_toc_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'EquationSource'` (and `EquationCapture(...)` rejects the old `images=` keyword once renamed)

- [ ] **Step 3: Implement**

In `src/web_toc/domain/models.py`, replace the existing `EquationCapture` dataclass and add the two new ones:

```python
@dataclass
class EquationSource:
    """One equation's real source, as the content JSON carries it - mathml
    is MathJax-ready markup; latex is the fallback for the rare node that
    has no mathml."""

    latex: str
    mathml: str | None = None


@dataclass
class MarkedEquation:
    """One `.equation-block` tagged on a saved page: `key` is its unique
    per-occurrence id (see equation_script.py), `node_id` is the content-
    JSON node id it was rendered from - the lookup key into a
    {node_id: EquationSource} map."""

    key: str
    node_id: str


@dataclass
class EquationCapture:
    """A saved page with each MathJax equation-block tagged and swapped for
    an <img> of itself. The images themselves are rendered separately, once
    per distinct node id, from the site's own latex/mathml (see
    equation_renderer.py) - not screenshotted per page."""

    html: str
    marked: list[MarkedEquation]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/domain/models.py tests/test_web_toc_models.py
git commit -m "feat(web_toc): add EquationSource/MarkedEquation, reshape EquationCapture"
```

*(This leaves `page_source.py` and `build_web_pages.py` broken until Tasks 4 and 8 update them — expected, and fixed within this same plan.)*

---

## Task 4: Web — mark/capture equations by node id instead of screenshotting

**Files:**
- Modify: `src/web_toc/parsing/equation_script.py`
- Modify: `src/web_toc/parsing/page_source.py:23-29,108,115-123,216-230`
- Test: `tests/test_web_toc_equation_capture.py` (rewrite)

**Interfaces:**
- Consumes: `EquationCapture`, `MarkedEquation` from Task 3.
- Produces: `PlaywrightPageSource.capture_equations(url) -> EquationCapture | None` now returns `marked: list[MarkedEquation]` instead of screenshotted `images`. Consumed by Task 8.

- [ ] **Step 1: Write the failing tests (full rewrite of the file)**

Replace `tests/test_web_toc_equation_capture.py` with:

```python
"""Tags each MathJax-rendered equation on a locally served page with its key
and node id, and swaps each for an <img> placeholder of itself - in a real
headless Chromium, over a page with the saved pages' real shell. The
fixture's `mjx-*` elements stand in for MathJax's CHTML output: a full-width
`mjx-container` around a tight `mjx-math` glyph box. Rendering the <img>'s
actual pixel content is a separate concern (see equation_renderer.py /
build_web_pages.py) - this only covers marking, sizing/positioning and the
swap."""

import asyncio

import pytest

from web_toc.parsing.equation_script import EQUATION_ASSET_DIR
from web_toc.parsing.local_page_server import serve_pages
from web_toc.parsing.page_source import PlaywrightPageSource

_EQUATION = """<div class="equation-block equation-block--{display}"{node_id}><span
class="equation-block__mathml" role="math" aria-label="{label}"><mjx-container class="MathJax"
style="display:{container}"><mjx-math style="display:inline-block;width:{w}px;height:{h}px;
background:#000"></mjx-math><mjx-assistive-mml><math><mi>W</mi></math></mjx-assistive-mml>
</mjx-container></span></div>"""


def _equation(display, label, w, h, node_id=""):
    return _EQUATION.format(
        display=display,
        node_id=f' data-node-id="{node_id}"' if node_id else "",
        label=label,
        container="block" if display == "block" else "inline-block",
        w=w,
        h=h,
    )


# A label with the raw whitespace runs the site's aria-labels carry.
_SPACED_LABEL = "W=w ×\n   4.9"

_PAGE = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{margin:0}}</style></head><body>
<main id="main-content"><div class="MainLayout"><main class="ui-ContentPanel">
<div id="s2.clause2">b) the following formula
{_equation("block", _SPACED_LABEL, 120, 30, "es1")}</div>
<div id="p3">Example {_equation("block", "0.5 kPa", 60, 20)} and
{_equation("inline", "l_c", 20, 10)}</div>
<div id="t1"><table><tr><th>Value of {_equation("inline", "C_w", 24, 12, "eg2")}</th></tr></table>
<table class="table-block__table--pinned-col"><tr><th>Value of
{_equation("inline", "C_w", 24, 12, "eg2")}</th></tr></table></div>
</main></div></main></body></html>"""

_PLAIN_PAGE = """<!DOCTYPE html><html><body><main><div><main class="ui-ContentPanel">
<div id="s1">No formulas here.</div></main></div></main></body></html>"""


async def _capture(base_url):
    async with PlaywrightPageSource() as source:
        return {
            "page": await source.capture_equations(f"{base_url}/page.html"),
            "plain": await source.capture_equations(f"{base_url}/plain.html"),
        }


async def _render(base_url):
    """The rewritten page, served back with placeholder PNGs, as a browser
    sees it."""
    async with PlaywrightPageSource() as source:
        tab = await source._context.new_page()
        await tab.goto(f"{base_url}/rewritten.html", wait_until="load")
        seen = await tab.evaluate(
            """() => [...document.querySelectorAll('img.equation-image')].map((img) => ({
              key: img.dataset.equation, owner: img.dataset.owner, alt: img.alt,
              loaded: img.complete && img.naturalWidth > 0,
              width: img.getBoundingClientRect().width,
              height: img.getBoundingClientRect().height,
            }))"""
        )
        mathjax_left = await tab.evaluate("document.querySelectorAll('mjx-container').length")
        await tab.close()
    return seen, mathjax_left


_PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\xa6-\xf9\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    pages_dir = tmp_path_factory.mktemp("web_pages")
    (pages_dir / "page.html").write_text(_PAGE)
    (pages_dir / "plain.html").write_text(_PLAIN_PAGE)
    with serve_pages(pages_dir) as base_url:
        result = asyncio.run(_capture(base_url))
        page = result["page"]
        (pages_dir / "rewritten.html").write_text(page.html)
        images_dir = pages_dir / "assets" / EQUATION_ASSET_DIR
        images_dir.mkdir(parents=True)
        for marked in page.marked:
            (images_dir / f"{marked.key}.png").write_bytes(_PLACEHOLDER_PNG)
        result["rendered"], result["mathjax_left"] = asyncio.run(_render(base_url))
    return result


def test_every_equation_is_marked_with_its_key_and_node_id(captured):
    # The site reuses a node id for the same formula in several places, so
    # the owner's id makes the key unique; one with no node id is "eq", and
    # a repeat within one owner is "-n". The pinned-column copy of a header
    # cell is the same equation again.
    by_key = {m.key: m.node_id for m in captured["page"].marked}
    assert sorted(by_key) == ["p3.eq", "p3.eq-2", "s2.clause2.es1", "t1.eg2"]
    assert by_key["s2.clause2.es1"] == "es1"
    assert by_key["t1.eg2"] == "eg2"
    assert by_key["p3.eq"] == ""  # no data-node-id on this block


def test_the_rewritten_page_shows_a_placeholder_in_place_of_mathjax(captured):
    seen, mathjax_left = captured["rendered"], captured["mathjax_left"]
    assert mathjax_left == 0
    assert all(img["loaded"] for img in seen)
    by_key = {img["key"]: img for img in seen}
    formula = by_key["s2.clause2.es1"]
    assert formula["owner"] == "s2.clause2"
    assert formula["alt"] == "W=w × 4.9"  # whitespace runs collapsed
    assert (formula["width"], formula["height"]) == (120, 30)
    assert by_key["p3.eq-2"]["owner"] == "p3"
    assert by_key["t1.eg2"]["owner"] == "t1"
    assert len(seen) == 5  # both copies of the pinned header cell


def test_the_rewritten_page_keeps_its_doctype_and_panel(captured):
    html = captured["page"].html
    assert html.startswith("<!DOCTYPE html>")
    assert 'class="ui-ContentPanel"' in html
    assert f'src="/web-assets/{EQUATION_ASSET_DIR}/s2.clause2.es1.png"' in html


def test_a_page_without_equations_is_left_alone(captured):
    assert captured["plain"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_toc_equation_capture.py -v`
Expected: FAIL — `AttributeError: 'EquationCapture' object has no attribute 'marked'` (still returns `images`)

- [ ] **Step 3: Implement**

In `src/web_toc/parsing/equation_script.py`, update the docstring's step 2 and `MARK_EQUATIONS_JS`:

```python
"""The in-browser equation capture run over each locally saved page.

The site renders every formula - the content JSON's `display`/`inline`
LaTeX/MathML nodes - with MathJax into a `.equation-block`: a
`mjx-container` of CHTML glyph boxes whose characters are CSS `::before`
content, plus a hidden MathML copy for screen readers. Each block is one
unit here:

1. MARK_EQUATIONS_JS tags every block still holding MathJax output with its
   owner - the nearest enclosing element with an id (the sentence/clause/
   table/note it belongs to) - and a key, `<owner id>.<data-node-id>`: the
   site reuses a content JSON node id for the same formula in several
   places, so the owner makes it unique. A block with no node id is
   `<owner id>.eq`; a repeat within one owner gets `-n` (the key is also
   the PNG's file name, so it stays within page_writer's safe set). Returns
   [{key, owner, nodeId}] in document order; a table's pinned-column copy
   of a header cell repeats its original's key. nodeId is the raw
   `data-node-id` (possibly ''), the lookup key into the site's own
   latex/mathml for that formula - rendering that content is a separate
   step (see equation_renderer.py), independent of this page.
2. SWAP_EQUATIONS_JS replaces each `mjx-container` with an
   `<img class="equation-image">` of that PNG at the size and position the
   glyphs had, and returns the whole page's HTML - so the saved page, the
   viewer and the layout pass all show the captured image.
"""
```

```python
MARK_EQUATIONS_JS = """() => {
  const root = document.querySelector('main.ui-ContentPanel');
  if (!root) return [];
  const seen = new Map();
  const marked = [];
  for (const block of root.querySelectorAll('.equation-block')) {
    if (!block.querySelector('mjx-container')) continue;
    const holder = block.parentElement.closest('[id]');
    const owner = holder && root.contains(holder) ? holder.id : '';
    const nodeId = block.dataset.nodeId || '';
    const base = [owner, nodeId || 'eq'].filter(Boolean).join('.');
    // Counted apart, so the n-th pinned copy repeats the n-th original's key.
    const pinned = !!block.closest('.table-block__table--pinned-col');
    const counter = `${pinned}|${base}`;
    seen.set(counter, (seen.get(counter) || 0) + 1);
    const n = seen.get(counter);
    const key = n === 1 ? base : `${base}-${n}`;
    block.dataset.equationKey = key;
    block.dataset.equationOwner = owner;
    marked.push({ key, owner, nodeId });
  }
  return marked;
}"""
```

(`SWAP_EQUATIONS_JS` is unchanged — it already only needs `block.dataset.equationKey`/`equationOwner`.)

In `src/web_toc/parsing/page_source.py`:

Replace the import block (lines 23-29):

```python
from web_toc.domain.models import EquationCapture, MarkedEquation, ScrapedPage
from web_toc.parsing.equation_script import MARK_EQUATIONS_JS, SWAP_EQUATIONS_JS
```

Delete `_screenshot_equations` (lines 115-123) entirely.

Replace `capture_equations` (lines 216-230):

```python
    async def capture_equations(self, url: str) -> EquationCapture | None:
        """Tags every MathJax equation on an already-saved, locally served
        page with its key and content-JSON node id, and swaps each for an
        <img> placeholder of itself (see equation_script.py); None if the
        page has none left to capture. Rendering the placeholder's actual
        pixel content happens separately, once per distinct node id across
        the whole site (see build_web_pages.py's capture_equations)."""
        tab = await self._context.new_page()
        try:
            await tab.goto(url, wait_until="load")
            await tab.evaluate("document.fonts.ready.then(() => null)")
            marked = await tab.evaluate(MARK_EQUATIONS_JS)
            if not marked:
                return None
            html = await tab.evaluate(SWAP_EQUATIONS_JS)
            return EquationCapture(
                html=html,
                marked=[MarkedEquation(key=e["key"], node_id=e["nodeId"]) for e in marked],
            )
        finally:
            await tab.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_equation_capture.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/equation_script.py src/web_toc/parsing/page_source.py tests/test_web_toc_equation_capture.py
git commit -m "feat(web_toc): mark equations by node id instead of screenshotting them"
```

*(`build_web_pages.py` still references the old `EquationCapture.images`/`_screenshot_equations` shape until Task 8 — expected.)*

---

## Task 5: Web — extract latex/mathml from the cached content JSON

**Files:**
- Create: `src/web_toc/parsing/equation_sources.py`
- Test: `tests/test_web_toc_equation_sources.py`

**Interfaces:**
- Consumes: `EquationSource` from Task 3.
- Produces: `equation_sources_in_content(content: dict) -> dict[str, EquationSource]`. Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_toc_equation_sources.py`:

```python
from web_toc.parsing.equation_sources import equation_sources_in_content


def test_finds_a_top_level_equation_node():
    content = {"id": "s1", "content": [{"type": "sentence", "id": "es1", "latex": "W=w"}]}
    sources = equation_sources_in_content(content)
    assert sources["es1"].latex == "W=w"
    assert sources["es1"].mathml is None


def test_finds_an_arbitrarily_nested_equation_node():
    # A formula can sit inside a sentence's clauses, or inside a table cell -
    # this must not assume a fixed shape.
    content = {
        "id": "s1",
        "content": [
            {
                "type": "table",
                "id": "t1",
                "rows": [{"cells": [{"id": "eg1", "latex": "l_c", "mathml": "<math/>"}]}],
            }
        ],
    }
    sources = equation_sources_in_content(content)
    assert sources["eg1"].latex == "l_c"
    assert sources["eg1"].mathml == "<math/>"


def test_a_node_with_an_empty_id_is_excluded():
    content = {"id": "s1", "content": [{"type": "sentence", "id": "", "latex": "x"}]}
    assert equation_sources_in_content(content) == {}


def test_no_equations_returns_an_empty_dict():
    assert equation_sources_in_content({"id": "s1", "content": []}) == {}


def test_a_node_with_no_latex_is_not_a_source():
    content = {"id": "s1", "content": [{"type": "sentence", "id": "es1", "text": "plain text"}]}
    assert equation_sources_in_content(content) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_toc_equation_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing.equation_sources'`

- [ ] **Step 3: Implement**

Create `src/web_toc/parsing/equation_sources.py`:

```python
"""Collects every equation's real latex/mathml source from the site's own
content JSON, so the rendered formula image comes from the site's own
markup rather than a screenshot of one particular page's MathJax output. An
equation node can sit arbitrarily deep - inside a sentence's clauses, inside
a table cell - so this walks the whole JSON structure instead of assuming a
fixed shape. Pure: no file or browser I/O (see source_cache.py for the
file-loading wrapper)."""

from web_toc.domain.models import EquationSource


def _nodes_with_latex(value: object) -> list[dict]:
    if isinstance(value, dict):
        found = [value] if "latex" in value and "id" in value else []
        for child in value.values():
            found += _nodes_with_latex(child)
        return found
    if isinstance(value, list):
        return [node for item in value for node in _nodes_with_latex(item)]
    return []


def equation_sources_in_content(content: dict) -> dict[str, EquationSource]:
    """{node id: EquationSource} for every latex-bearing node in one page's
    content JSON, however deeply nested."""
    return {
        node["id"]: EquationSource(latex=node["latex"], mathml=node.get("mathml"))
        for node in _nodes_with_latex(content)
        if node["id"]
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_equation_sources.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/equation_sources.py tests/test_web_toc_equation_sources.py
git commit -m "feat(web_toc): extract equation latex/mathml from content JSON nodes"
```

---

## Task 6: Web — load cached equation sources from disk

**Files:**
- Modify: `src/web_toc/output/source_cache.py`
- Test: `tests/test_web_toc_source_cache.py` (already exists — append to it)

**Interfaces:**
- Consumes: `equation_sources_in_content` from Task 5.
- Produces: `load_cached_equation_sources(source_dir: Path) -> dict[str, EquationSource]`. Consumed by Task 8.

- [ ] **Step 1: Write the failing test**

Append to the test file covering `source_cache.py`:

```python
import json

from web_toc.output.source_cache import load_cached_equation_sources


def test_load_cached_equation_sources_merges_every_content_file(tmp_path):
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "s1.json").write_text(
        json.dumps({"id": "s1", "content": [{"id": "es1", "latex": "W=w"}]})
    )
    (content_dir / "s2.json").write_text(
        json.dumps({"id": "s2", "content": [{"id": "eg1", "latex": "l_c", "mathml": "<math/>"}]})
    )

    sources = load_cached_equation_sources(tmp_path)

    assert sources["es1"].latex == "W=w"
    assert sources["eg1"].mathml == "<math/>"


def test_load_cached_equation_sources_with_no_content_dir_returns_empty(tmp_path):
    assert load_cached_equation_sources(tmp_path) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_toc_source_cache.py -v -k load_cached_equation_sources`
Expected: FAIL — `ImportError: cannot import name 'load_cached_equation_sources'`

- [ ] **Step 3: Implement**

In `src/web_toc/output/source_cache.py`, add the import and the function:

```python
from web_toc.domain.models import EquationSource
from web_toc.parsing.equation_sources import equation_sources_in_content
```

```python
def load_cached_equation_sources(source_dir: Path) -> dict[str, EquationSource]:
    """Merges every cached content JSON's equation sources into one lookup -
    the site reuses one node id for the same formula in several places, so a
    single global map (not one per page) is enough. Empty if the content
    directory doesn't exist yet."""
    content_dir = Path(source_dir) / CONTENT_DIR
    if not content_dir.is_dir():
        return {}
    sources: dict[str, EquationSource] = {}
    for path in sorted(content_dir.glob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        sources.update(equation_sources_in_content(content))
    return sources
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_source_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/output/source_cache.py tests/test_web_toc_source_cache.py
git commit -m "feat(web_toc): load cached equation sources from the content JSON mirror"
```

---

## Task 7: Web — async MathJax equation renderer

**Files:**
- Create: `src/web_toc/parsing/equation_renderer.py`
- Test: `tests/test_web_toc_equation_renderer.py`

**Interfaces:**
- Consumes: `EquationSource` from Task 3.
- Produces: `EquationRenderer` — `async with EquationRenderer(device_scale_factor=...) as renderer: await renderer.render(source: EquationSource, output_path: Path) -> None`, raising `ValueError` if MathJax fails to typeset. Consumed by Task 8.

This ports `src/equation_export/rendering/mathjax_renderer.py`'s proven approach to the async Playwright API already used everywhere else in `web_toc`, and adds the LaTeX-fallback wrapping (mathml is used directly when present; mathml is cleaner and more reliable than the site's own latex export, so it's tried first — see the design spec).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_toc_equation_renderer.py`:

```python
"""Real MathJax rendering in a headless browser - no network beyond the
MathJax CDN bundle every page in this pipeline already loads."""

import asyncio

import pytest

from web_toc.domain.models import EquationSource
from web_toc.parsing.equation_renderer import EquationRenderer


def _render(source: EquationSource, path):
    async def go():
        async with EquationRenderer() as renderer:
            await renderer.render(source, path)

    asyncio.run(go())


def test_renders_mathml_to_a_png(tmp_path):
    target = tmp_path / "eq.png"
    _render(EquationSource(latex="x", mathml="<math><mi>x</mi></math>"), target)
    assert target.read_bytes().startswith(b"\x89PNG")


def test_falls_back_to_latex_when_mathml_is_missing(tmp_path):
    target = tmp_path / "eq.png"
    _render(EquationSource(latex="x^2"), target)
    assert target.read_bytes().startswith(b"\x89PNG")


def test_normalizes_the_sites_double_escaped_backslashes_in_latex_fallback(tmp_path):
    # The site's own latex export double-escapes commands like \\times - a
    # correctly-normalized double-escaped string must render identically to
    # the already-correct single-backslash form, not merely "without
    # crashing" (MathJax tolerates plenty of malformed input silently).
    normalized = tmp_path / "normalized.png"
    doubled = tmp_path / "doubled.png"
    _render(EquationSource(latex="a\\times b"), normalized)
    _render(EquationSource(latex="a\\\\times b"), doubled)
    assert doubled.read_bytes() == normalized.read_bytes()


def test_raises_value_error_when_mathjax_cannot_typeset(tmp_path):
    target = tmp_path / "eq.png"
    with pytest.raises(ValueError):
        _render(EquationSource(latex="", mathml="<not-math>not real markup<"), target)


def test_renders_several_equations_in_sequence_on_one_shared_instance(tmp_path):
    async def go():
        async with EquationRenderer() as renderer:
            await renderer.render(EquationSource(latex="x", mathml="<math><mi>x</mi></math>"), tmp_path / "a.png")
            await renderer.render(EquationSource(latex="y", mathml="<math><mi>y</mi></math>"), tmp_path / "b.png")

    asyncio.run(go())
    assert (tmp_path / "a.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "b.png").read_bytes().startswith(b"\x89PNG")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_toc_equation_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing.equation_renderer'`

- [ ] **Step 3: Implement**

Create `src/web_toc/parsing/equation_renderer.py`:

```python
"""Renders one equation's real source (mathml, or latex as a fallback) to a
standalone PNG via a headless-browser MathJax typeset - the same MathJax
build the live site loads, so the rendered glyphs match what a visitor
sees, independent of any particular page's own on-screen rendering."""

from pathlib import Path
from types import TracebackType

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from web_toc.domain.models import EquationSource

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
_TYPESET_SCRIPT = f"""(markup) => {{
    const target = document.getElementById("{_TARGET_ELEMENT_ID}");
    MathJax.typesetClear([target]);
    target.innerHTML = markup;
    return MathJax.typesetPromise([target]);
}}"""


def _normalize_latex(latex: str) -> str:
    """The site's own latex export double-escapes some commands (two
    literal backslashes before e.g. `times`/`leq`) - confirmed by comparing
    against the same entry's plainText field. Collapse back to the single
    backslash MathJax expects."""
    return latex.replace("\\\\", "\\")


def _as_markup(source: EquationSource) -> str:
    """mathml is already a `<math>` element MathJax recognizes directly; a
    latex-only fallback needs MathJax's own TeX input script wrapper."""
    if source.mathml is not None:
        return source.mathml
    return f'<script type="math/tex; mode=display">{_normalize_latex(source.latex)}</script>'


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
            await self._page.evaluate(_TYPESET_SCRIPT, markup)
            await self._page.locator(_TARGET_SELECTOR).screenshot(
                path=str(output_path), timeout=_TYPESET_TIMEOUT_MS
            )
        except PlaywrightError as exc:
            raise ValueError(f"MathJax did not typeset: {markup!r}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_equation_renderer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/equation_renderer.py tests/test_web_toc_equation_renderer.py
git commit -m "feat(web_toc): add async MathJax equation renderer"
```

---

## Task 8: Web — render marked equations from their real source in build_web_pages.py

**Files:**
- Modify: `src/build_web_pages.py:39-68,180-209,266-283`
- Test: `tests/test_build_web_pages.py`

**Interfaces:**
- Consumes: `EquationRenderer` (Task 7), `load_cached_equation_sources` (Task 6), `EquationSource`/`MarkedEquation`/`EquationCapture` (Task 3), `PlaywrightPageSource.capture_equations` (Task 4).

Note on dependency injection: `build_web_pages.py` already instantiates `PlaywrightPageSource`/`HttpxWebSource` inline and relies on tests patching the class reference (`patch("build_web_pages.PlaywrightPageSource", ...)`) rather than constructor injection — this task follows that same established pattern for `EquationRenderer`, per CLAUDE.md's "follow existing patterns" guidance, rather than introducing a new DI parameter.

- [ ] **Step 1: Write the failing tests**

In `tests/test_build_web_pages.py`:

Change the import line (near the top):

```python
from web_toc.domain.models import EquationCapture, MarkedEquation, ScrapedPage
```

Add two equation-bearing nodes to `_SECTION_CONTENT` (so the fake content JSON has real latex to resolve against):

```python
_SECTION_CONTENT = {
    "id": "nbc.divA.part1.sect1",
    "content": [
        {
            "type": "table",
            "id": "nbc.divA.part1.sect1.table1",
            "structure": {"header_rows": [{}], "body_rows": [{}, {}]},
        },
        {"type": "figure", "id": "nbc.divA.part1.sect1.figure1", "graphic": {"src": "g/f1"}},
        {"type": "sentence", "id": "es1", "latex": "W=w"},
        {"type": "sentence", "id": "eq1", "latex": "l_c"},
    ],
}
```

Add a fake renderer near the other fakes (after `_FakeHttp`):

```python
class _FakeRenderer:
    """Deterministic stand-in for EquationRenderer - no real MathJax/browser
    needed to test the orchestration wiring."""

    def __init__(self, *, fail_for=frozenset()):
        self._fail_for = fail_for

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def render(self, source, output_path):
        if source.latex in self._fail_for:
            raise ValueError(f"boom: {source.latex}")
        output_path.write_bytes(f"png-for-{source.latex}".encode())
```

Replace `_SECTION_CAPTURE` and the three equation tests (the ones currently reading `_SECTION_CAPTURE`/`EquationCapture(... images=...)`):

```python
_SECTION_CAPTURE = EquationCapture(
    html='<html><img class="equation-image" src="/web-assets/equations/es1.png"></html>',
    marked=[
        MarkedEquation(key="es1", node_id="es1"),
        MarkedEquation(key="nbc.divA.part1.sect1.eq1", node_id="eq1"),
    ],
)


def test_run_saves_each_rendered_equation_for_the_page_and_for_comparison(tmp_path):
    captures = {"nbc.divA.part1.sect1.html": _SECTION_CAPTURE}
    browser = _FakeBrowser(_default_pages(), captures=captures)
    with patch("build_web_pages.EquationRenderer", return_value=_FakeRenderer()):
        out = _build(tmp_path, browser, _content_http())

    expected = {"es1": b"png-for-W=w", "nbc.divA.part1.sect1.eq1": b"png-for-l_c"}
    for key, png in expected.items():
        assert (out / "assets" / "equations" / f"{key}.png").read_bytes() == png
        assert (tmp_path / "web_images" / "equations" / f"{key}.png").read_bytes() == png


def test_run_rewrites_a_page_with_equations_before_measuring_it(tmp_path):
    captures = {"nbc.divA.part1.sect1.html": _SECTION_CAPTURE}
    browser = _FakeBrowser(_default_pages(), captures=captures)

    with patch("build_web_pages.EquationRenderer", return_value=_FakeRenderer()):
        out = _build(tmp_path, browser, _content_http())

    assert (out / "nbc.divA.part1.sect1.html").read_text() == _SECTION_CAPTURE.html
    assert "equation-image" not in (out / "nbc.divA.part1.html").read_text()
    kinds = [kind for kind, _ in browser.local_calls]
    assert kinds == ["capture", "capture", "layout", "layout"]


def test_run_skips_an_equation_whose_key_is_not_a_safe_file_name(tmp_path, capsys):
    capture = EquationCapture(
        html="<html></html>",
        marked=[MarkedEquation(key="../evil", node_id="es1"), MarkedEquation(key="es1", node_id="es1")],
    )
    browser = _FakeBrowser(_default_pages(), captures={"nbc.divA.part1.sect1.html": capture})

    with patch("build_web_pages.EquationRenderer", return_value=_FakeRenderer()):
        out = _build(tmp_path, browser, _content_http())

    assert sorted(p.name for p in (out / "assets" / "equations").iterdir()) == ["es1.png"]
    assert "skipped equation '../evil'" in capsys.readouterr().err


def test_run_skips_an_equation_with_no_cached_source_and_keeps_the_rest(tmp_path, capsys):
    capture = EquationCapture(
        html="<html></html>",
        marked=[
            MarkedEquation(key="es1", node_id="es1"),
            MarkedEquation(key="missing1", node_id="no-such-node"),
            # A block with no data-node-id at all marks with node_id="" -
            # must be skipped the same way, not crash on an empty lookup key.
            MarkedEquation(key="noid1", node_id=""),
        ],
    )
    browser = _FakeBrowser(_default_pages(), captures={"nbc.divA.part1.sect1.html": capture})

    with patch("build_web_pages.EquationRenderer", return_value=_FakeRenderer()):
        out = _build(tmp_path, browser, _content_http())

    assert (out / "assets" / "equations" / "es1.png").exists()
    assert not (out / "assets" / "equations" / "missing1.png").exists()
    assert not (out / "assets" / "equations" / "noid1.png").exists()
    err = capsys.readouterr().err
    assert "skipped equation 'missing1'" in err
    assert "skipped equation 'noid1'" in err


def test_run_skips_an_equation_the_renderer_fails_on_and_keeps_the_rest(tmp_path, capsys):
    capture = EquationCapture(
        html="<html></html>",
        marked=[
            MarkedEquation(key="es1", node_id="es1"),
            MarkedEquation(key="nbc.divA.part1.sect1.eq1", node_id="eq1"),
        ],
    )
    browser = _FakeBrowser(_default_pages(), captures={"nbc.divA.part1.sect1.html": capture})

    with patch("build_web_pages.EquationRenderer", return_value=_FakeRenderer(fail_for={"l_c"})):
        out = _build(tmp_path, browser, _content_http())

    assert (out / "assets" / "equations" / "es1.png").exists()
    assert not (out / "assets" / "equations" / "nbc.divA.part1.sect1.eq1.png").exists()
    assert "skipped equation 'nbc.divA.part1.sect1.eq1'" in capsys.readouterr().err


def test_run_resolves_two_keys_sharing_the_same_node_id_independently(tmp_path):
    capture = EquationCapture(
        html="<html></html>",
        marked=[
            MarkedEquation(key="t1.eg1", node_id="eq1"),
            MarkedEquation(key="t2.eg1", node_id="eq1"),
        ],
    )
    browser = _FakeBrowser(_default_pages(), captures={"nbc.divA.part1.sect1.html": capture})

    with patch("build_web_pages.EquationRenderer", return_value=_FakeRenderer()):
        out = _build(tmp_path, browser, _content_http())

    assert (out / "assets" / "equations" / "t1.eg1.png").read_bytes() == b"png-for-l_c"
    assert (out / "assets" / "equations" / "t2.eg1.png").read_bytes() == b"png-for-l_c"
```

Delete the old `test_run_saves_each_captured_equation_for_the_page_and_for_comparison` test (replaced above).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_build_web_pages.py -v`
Expected: FAIL — `AttributeError`/`TypeError` from the old `EquationCapture(images=...)` call sites and `_save_equations` signature in `build_web_pages.py`

- [ ] **Step 3: Implement**

In `src/build_web_pages.py`:

Add `import tempfile` to the top-level stdlib imports (alongside the existing `import json`/`import sys`).

Change the existing `from web_toc.domain.models import EquationCapture, ScrapedPage, WebNode` line to:

```python
from web_toc.domain.models import EquationCapture, EquationSource, ScrapedPage, WebNode
```

Change the existing `from web_toc.output.source_cache import cache_contents, write_navigation, write_snapshot` line to:

```python
from web_toc.output.source_cache import (
    cache_contents,
    load_cached_equation_sources,
    write_navigation,
    write_snapshot,
)
```

Add a new import line:

```python
from web_toc.parsing.equation_renderer import EquationRenderer
```

Replace `_save_equations` (lines 180-194):

```python
def _save_equations(pages_dir: Path, images_dir: Path, images: dict[str, bytes]) -> None:
    """Each PNG goes to the page asset mirror (what the rewritten page
    shows) and to web_images/ (next to the figures, for comparing with the
    PDF's formula images)."""
    for key, png in images.items():
        targets = [
            citation_file(directory / EQUATION_ASSET_DIR, key, ".png")
            for directory in (pages_dir / "assets", images_dir)
        ]
        if None in targets:
            print(f"  skipped equation {key!r} (not a safe file name)", file=sys.stderr)
            continue
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png)
```

Replace `capture_equations` and add the two new helper functions (lines 197-208):

```python
async def _render_one_equation(
    renderer: EquationRenderer, key: str, node_id: str, sources: dict[str, EquationSource]
) -> bytes | None:
    source = sources.get(node_id) if node_id else None
    if source is None:
        print(f"  skipped equation {key!r} (no cached latex/mathml for {node_id!r})", file=sys.stderr)
        return None
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "eq.png"
        try:
            await renderer.render(source, target)
        except ValueError as exc:
            print(f"  skipped equation {key!r} ({exc})", file=sys.stderr)
            return None
        return target.read_bytes()


async def _render_marked_equations(
    node_id_by_key: dict[str, str], sources: dict[str, EquationSource]
) -> dict[str, bytes]:
    images: dict[str, bytes] = {}
    async with EquationRenderer(device_scale_factor=EQUATION_SCALE) as renderer:
        for key, node_id in node_id_by_key.items():
            png = await _render_one_equation(renderer, key, node_id, sources)
            if png is not None:
                images[key] = png
    return images


async def capture_equations(
    pages_dir: Path, images_dir: Path, citations: list[str], source_dir: Path
) -> None:
    """Swaps every MathJax equation on the saved pages for a PNG rendered
    from the site's own latex/mathml, rather than a screenshot of this
    particular page's own on-screen rendering."""
    results = await _over_local_pages(
        pages_dir, citations, lambda browser, url: browser.capture_equations(url)
    )
    captured = [(citation, capture) for citation, capture in results if capture is not None]
    node_id_by_key = {m.key: m.node_id for _, capture in captured for m in capture.marked}
    sources = load_cached_equation_sources(source_dir)
    images = await _render_marked_equations(node_id_by_key, sources)
    for citation, capture in captured:
        write_page(pages_dir, citation, capture.html)
    _save_equations(pages_dir, images_dir, images)
```

Update the call site in `run()` (around line 281):

```python
    await capture_equations(pages_dir, out / "web_images", list(manifest), out / "web_source")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_web_pages.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/build_web_pages.py tests/test_build_web_pages.py
git commit -m "feat(build_web_pages): render equations from their own latex/mathml"
```

---

## Task 9: Retire the unintegrated equation_export module

**Files:**
- Delete: `src/equation_export/` (all files)
- Delete: `src/export_equations.py`
- Delete: `tests/test_equation_export_domain_models.py`, `tests/test_equation_export_equation_source.py`, `tests/test_equation_export_latex_renderer.py`, `tests/test_equation_export_mathjax_renderer.py`, `tests/test_equation_export_png_exporter.py`, `tests/test_export_equations.py`
- Modify: `CLAUDE.md`

**Interfaces:** None — this module's one useful piece of logic (MathJax headless rendering) was already ported to `web_toc/parsing/equation_renderer.py` in Task 7, with its own tests. Nothing in the codebase imports `equation_export` after Task 8.

- [ ] **Step 1: Confirm nothing still imports it**

Run: `grep -rn "equation_export" src/ tests/ --include="*.py" | grep -v "^tests/test_equation_export\|^tests/test_export_equations"`
Expected: no output (only the files being deleted reference it)

- [ ] **Step 2: Delete the module and its tests**

```bash
git rm -r src/equation_export src/export_equations.py
git rm tests/test_equation_export_domain_models.py tests/test_equation_export_equation_source.py \
       tests/test_equation_export_latex_renderer.py tests/test_equation_export_mathjax_renderer.py \
       tests/test_equation_export_png_exporter.py tests/test_export_equations.py
```

- [ ] **Step 3: Run the full suite to confirm nothing broke**

Run: `pytest -q`
Expected: PASS, with the equation_export test count no longer present

- [ ] **Step 4: Update CLAUDE.md**

Before deleting anything in Step 2, run `pytest --collect-only -q | tail -1` and note the total collected-test count. After Step 2's deletion, run it again and note the new total — these two numbers are what go in the sentence below (do not guess them).

In the "Working notes" section of `CLAUDE.md`, add a line after the existing "A real test suite (...)" paragraph:

```markdown
- `src/equation_export/` - an earlier, standalone LaTeX-export experiment that fetched the site's
  `equation-map.json` directly and was never wired into `web_toc`/`comparison` - was retired once this
  work found the same latex/mathml already sitting in the content JSON `build_web_pages.py` caches, and
  ported the module's one load-bearing piece, MathJax headless rendering, into
  `src/web_toc/parsing/equation_renderer.py` (see
  `docs/superpowers/specs/2026-10-12-equation-image-extraction-design.md`). Test count: <before> before
  retirement, <after> after.
```

Replace `<before>`/`<after>` with the two real numbers measured above.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "chore: retire the unintegrated equation_export module"
```

---

## Task 10: Full verification pass (Definition of Done)

**Files:** None (verification only).

- [ ] **Step 1: Lint and format**

```bash
ruff check --fix . && ruff format .
```
Expected: no remaining issues; commit any auto-fixes.

- [ ] **Step 2: Complexity check**

```bash
radon cc -s -n B .
```
Expected: no function introduced or touched by this plan graded C or worse. If `merge_equation_fragments`/`_find_stackable_pair` or `_render_marked_equations`/`_render_one_equation` grade C+, refactor before proceeding.

- [ ] **Step 3: Dead code check**

```bash
vulture .
```
Expected: no new unused code — specifically confirm `GLYPHS_SELECTOR`/`MARKED_SELECTOR` are still used (inside `equation_script.py`'s own JS strings) even though `page_source.py` no longer imports them, and that nothing from the deleted `equation_export` module is still referenced.

- [ ] **Step 4: Full test suite**

```bash
pytest --cov=.
```
Expected: all green; `src/mo_toc/`, `src/web_toc/`, `src/build_web_pages.py` branches touched by this plan are covered.

- [ ] **Step 5: JS test suite (if the equation/layout JS changed)**

```bash
pytest tests/test_viewer_js.py -q
```
Expected: PASS — confirms `equation_script.py`'s `MARK_EQUATIONS_JS` change didn't break any pure-JS helper test that inlines it.

- [ ] **Step 6: Commit any fixes from this pass**

```bash
git add -A
git commit -m "chore: address ruff/radon/vulture findings from equation image extraction work"
```

(Skip this commit if Steps 1-5 found nothing to fix.)
