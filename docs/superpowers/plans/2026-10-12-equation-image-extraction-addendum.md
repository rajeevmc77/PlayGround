# Equation Image Extraction — Addendum: classify PDF equations from the PDF's own tag

> Addendum to `2026-10-12-equation-image-extraction.md` (Tasks 1-10, done). Spec amendment below. Tasks here are numbered 11-12.

**Why:** Task 10's real-PDF run showed the PDF-side vector merge (Tasks 1-2) changes 0 of 626 images: no formula in this PDF is vector-drawn. The real gap is classification. The PDF index has 103 `Eq` images against 133 web equations (84 keys in common). Investigation (`scratchpad/pdf_equation_gap_findings.md`, scripts in `scratchpad/eqgap/`, esp. `structmap.py`, `simulate.py`) found: **the PDF is tagged and exactly 129 `/Figure` structure elements carry `/Alt (EQUATION)`** — the 84 current Eq rasters, 38 formulas wrongly marked `decorative` (small inline symbols like N̄, s̄ᵤ, f′c), and 7 formulas keyed as Figures (table-cell formulas, one caption-captured, one taller than `MAX_EQUATION_HEIGHT`). Every formula is already extracted complete as a 1-bit raster; they are just not keyed `Eq`. 17 of the 19 PDF-only `Eq` keys are vector crops of table rows/forms (false positives that shift later keys).

**Goal:** make every EQUATION-tagged PDF image an `Eq` image (keyed `…EqN`, linked to the web equation by the shared unified key), without relying on shape heuristics; stop keying vector crops as `Eq`.

**Spec amendment:** the spec's PDF-side section (stacked-fragment merge) stays as built (harmless, no effect on this PDF) - *later removed by Ruling 11; see the spec's Amendment*. Add: *PDF equations are identified by the PDF's structure-tree `/Alt (EQUATION)` tag when present; the shape heuristic (`is_equation_shaped`) remains only as the fallback for untagged raster images; a vector crop is never classified as an equation.*

## Global Constraints
- Same as the main plan: TDD (failing test first), functions <=20 lines, complexity <=6, nesting <=2, Clean Architecture (domain logic free of PDF-library specifics; the PDF library stays inside `PdfSource`), never weaken/delete existing tests to pass (a test that asserts the OLD classification may be updated only when the new behaviour is the intended one — say so in the report), ruff/radon/vulture/pytest per CLAUDE.md.
- Worktree only; the main checkout's `output/` is shared — never write there; measure in a scratch dir.

## Task 11: read the tag, classify by it

**Files (find the exact ones by reading; expected):**
- `src/mo_toc/parsing/pdf_source.py` (+ its fake in tests): new method on `PdfSource`, e.g. `page_image_alts(page_index) -> dict`/list giving each image placement's structure `/Alt` (bbox or xref + alt). Mapping (from `eqgap/structmap.py`): page content stream has `/Figure <</MCID n>> BDC … cm /ImX Do … EMC`; map MCID -> structure element `/Figure` with `/Pg` + `/K` -> `/Alt`. Images not found (Form XObjects / no MCID: 14 figures) simply get no alt.
- `src/mo_toc/parsing/image_extractor.py`: `RawImage` carries the alt (new field, default None so nothing else breaks); also check `src/mo_toc/parsing/parallel_extraction.py` (worker processes — the field must survive pickling) and the `ImageAsset` model/`write_images`/JSON writer so `bcbc_pdf.json` records it (e.g. `alt` or `tagged_equation: bool` — pick one, keep JSON backward compatible, viewer/comparison must not break on the new key).
- `src/build_mo_toc.py` (`partition_equations`, `_is_equation`, `_is_decorative`, `drop_images_over_tables`, caption `match_images` interplay) and `src/mo_toc/domain/image_classification.py`.
- `src/shared/numbering.py` only if the `decorative` skip needs it — prefer fixing the classification upstream so tagged equations are never `decorative`.
- Tests under `tests/` (`test_build_mo_toc.py`, `test_image_classification.py`, `test_image_extractor.py`, `test_parallel_extraction.py`, fake `PdfSource`s, plus a new test file for the tag reader using a tiny PDF built in-test with PyMuPDF if feasible — otherwise a slow real-PDF test on known pages, e.g. page 1563 has no image; use the pages of B.4.1.6.10 / AppD p1616).

**Behaviour (acceptance, each pinned by a test):**
1. A tagged-EQUATION image is classified `Eq` before and regardless of: `decorative`, a Figure caption claim, overlap with a table bbox, `MAX_EQUATION_HEIGHT`, shape. It is never `decorative` (so `number_images` keys it).
2. A Figure caption must not be consumed by a tagged equation: when the nearest image to a caption is a tagged equation, the caption goes to the next non-equation image (B.4.1.6.12: the formula above "Figure 4.1.6.12." must stop taking the caption).
3. Untagged images keep today's behaviour EXCEPT: a vector-kind crop is never `Eq` (equation-shaped vector crops become Figures); an untagged raster that is equation-shaped (and not decorative/captioned/in a table) is still `Eq` (fallback; keeps B.A-9.23.13.2.(3)).
   *Superseded by Ruling 10: such vector crops are left unkeyed (neither Eq nor Fig).*
4. Boundaries: empty alt, alt other than EQUATION (e.g. an `.eps` path, "automatically generated"), image with no structure element, page with no structure tree, PDF with no `StructTreeRoot` at all -> behaves exactly like today. Match on the alt text exactly `EQUATION` (case-sensitive, trimmed) — pin with tests.
5. The tag reader must be robust: a malformed/absent struct tree or content stream never crashes extraction (return no alts).

**Real-document acceptance (Task 12 measures it):** PDF `Eq` count ~131 (129 tagged + untagged-raster fallback), unified keys in common with `output/bcbc_web.json` equations ~129 (was 84); remaining web-only ~4 (AppC.Eq3/4 text-layer shift, B.4.1.8.2.Eq3/4 site orphans), PDF-only ~2 (B.A-9.23.3.1.(2).Eq1/2).

## Task 12: measure on the real PDF, check the comparison, document

- Build the PDF index into a scratch dir (see CLAUDE.md "Working notes": symlink the web inputs into the scratch dir; `src/build_mo_toc.py --output-dir <dir>`), compare against the existing `output/bcbc_pdf.json`: Eq/Fig counts, the keys in common with the web equations, web-only/PDF-only lists, and the figure keys that shifted (the 7 formerly Fig-keyed formulas free their Fig numbers — list which Fig keys changed). Run `src/build_comparison.py --output-dir <dir>` into the same scratch dir and compare equation/figure pass/fail counts before (baseline from the existing output) vs after; report any figure that newly fails or newly passes and why.
- Update `ai_docs/2026-09-27-site-discrepancies-report.md` with the two AppC text-layer formulas (MathJax on the site, body text in the PDF) and the two B.4.1.8.2 site-only orphan images.
- Update CLAUDE.md (item 2 and Working notes): PDF equations are identified by the tag; add the measured numbers; note the vector merge (`merge_equation_fragments`) is a no-op on the current PDF.
- Full DoD (ruff scoped, radon, vulture, `pytest --cov`, slow real-PDF tests).
