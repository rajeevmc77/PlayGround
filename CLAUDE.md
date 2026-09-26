# CLAUDE.md

## Project
A playground for trying out Google Workspace/Drive APIs and PDF structural parsing. Two
independent tools live here:

1. **Directory/Drive web app** (`app.py`) — FastAPI app with "Sign in with Google" (OAuth2).
   Once logged in, a user can:
   - List all names/emails in the `aot-technologies.com` Workspace directory (People API,
     falls back to Admin SDK Directory API).
   - List the subfolders of a fixed Google Drive folder.
   - Cross-check directory users against Drive folder names by fuzzy name match (word-by-word
     similarity, not raw character sequence matching — see `name_similarity` in `app.py` for
     why: naive whole-string matching produced false positives on short names) — surfacing
     users with no matching folder, and folders with no matching active user.

2. **MO Package TOC + Image viewer** (`src/mo_toc/`) — parses
   `MO Package BCBC MRK signed.pdf` into a full hierarchical index (Volume → FrontMatter /
   Division → Part → Section → Subsection → Article → Sentence → Clause → Subclause,
   with each Part's "Notes to Part" → Note nested under that Part as its last child,
   Appendix chain, BackMatter) plus a flat Table/Figure caption index
   and a full embedded-image index — every node carries a page number and a precise
   bounding box. Served as JSON/Markdown (`src/build_mo_toc.py`) and through an
   interactive web viewer (`src/serve_mo_toc.py`) with two tabs: "Table of Contents - Both"
   (the PDF tree driving the PDF page and the matching saved web page side by side, each
   highlighting the clicked location - the web box is measured live from the node's
   `xpath` in the saved page, hugging its rendered text; Figures / Tables / Equations / Text / Images filters
   show or hide those rows — headings always stay, and an image whose row is hidden moves up
   to the nearest row still shown) and "Compare" (PDF vs web images).
   See `ai_docs/2026-09-20-mo-toc-viewer-design.md` for the full design.
   A second, independent index (`src/web_toc/`, `src/build_web_toc.py`) is sourced from the
   BC Building Code website instead of the PDF, and feeds the viewer's web side.
   It is built in two steps (see `ai_docs/2026-09-25-web-toc-local-scrape-design.md`):
   `src/build_web_pages.py` is the **only** step that touches the network — it caches the
   site's navigation tree + every content JSON under `output/web_source/` (with
   `snapshot.json` recording the version/effective date), renders each of the site's own
   reading pages in headless Chromium (Playwright, many tabs concurrently) scrolled until every
   table row the JSON lists has lazy-loaded (long tables load 120 rows per scroll; the run
   exits non-zero if a table stays short), saves its `main.ui-ContentPanel` to
   `output/web_pages/<citation>.html`, mirrors every stylesheet/font/image under
   `output/web_pages/assets/` (plus `site-nav.css`), downloads figures to `output/web_images/`,
   then serves the saved pages locally, screenshots every MathJax-rendered equation to a PNG
   (`output/web_images/equations/` and `output/web_pages/assets/equations/`), rewrites each
   saved page to show those PNGs in place of MathJax, and measures the pages into
   `output/web_pages/<citation>.layout.json` (once the page's web fonts have loaded -
   measured in the fallback font, text wraps differently and every bbox below drifts;
   `--measure-only` re-runs just this step, offline, over the pages already saved). Each equation becomes an `images` entry with
   `kind: "equation"` (figures are `kind: "figure"`), keyed `…EqN`, for comparing with the
   PDF's formula images. `src/build_web_toc.py` then runs **offline**:
   structure/numbering from the cached JSON (read as of the snapshot date — revised items
   carry dated `revisions`), and each node's rendered text plus
   `location: {page_file, xpath, bbox}` from the layout files. Every `xpath` starts at the
   saved page's content panel `/html/body/main/div/main` and every `bbox` is CSS px from that
   panel's top-left corner, so the PDF page and the saved HTML can be shown side by side.
   Subsection/article views are cut from their section page the way the site
   does it, so only ~136 pages are scraped. Both indexes key every node by `unified_number`
   (built from the code's own numbering, identical in both files for the same node); heading
   nodes also carry a `heading` field with the literal heading words, e.g. `Part 1`.

A standalone CLI companion, `src/check_directory_access.py`, checks (outside the web app) 
whether a given account can list the Workspace directory via the People API vs. the Admin SDK,
and prints which path works and why.

## Folder structure
- `app.py` — the FastAPI app; stays in the project root (its own entry point).
- `src/` — Python modules and scripts. `mo_toc/` is the main indexing library (see item 2 above).
  `check_directory_access.py` is a standalone CLI tool (see below). All scripts anchor their
  file paths (credentials, token, PDF, output) to the project root via
  `Path(__file__).resolve().parent.parent`, not the current working directory, so they run
  correctly regardless of where they're invoked from.
- `web_toc/` — the BC Building Code website indexing library (mirrors `mo_toc/`'s
  domain/parsing/output split), sourced from `https://dev.buildingcode.gov.bc.ca` rather
  than a local PDF. `build_web_pages.py` snapshots the site locally; `build_web_toc.py`
  builds the index offline from that snapshot.
- `shared/` — small pure-function helpers with no dependency on either indexing
  library, shared between `mo_toc/` and `web_toc/` (currently just the unified
  document-level numbering algorithm used by both `build_mo_toc.py` and
  `build_web_toc.py`).
- `data/` — input source files, e.g. `MO Package BCBC MRK signed.pdf`, `bcbc_2024.pdf`.
- `output/` — everything a program run produces. Regenerated by re-running the producing
  script; safe to delete and rebuild.
- `ai_docs/` — Markdown written by Claude directly as part of analysis or solution-building
  (design notes, reports) — distinct from `output/`, which is only ever machine-generated by
  running a script.
- `Archive DO NOT Refer/` — retired code and its generated output from before the
  2026-09-20 rewrite (`bcbc_mo_index.py`, `bcbc2024_index.py`, `extract_figures.py`,
  `extract_figures_2024.py`). Not imported by anything active — kept for historical
  reference only, per its name: do not import from or copy logic out of it into new work.
- Root also holds: `credentials.json` / `token.json` (OAuth secrets — never commit these if
  this ever becomes a git repo), `requirements.txt`, `Readme.md`.

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the web app (needs a Web-application-type OAuth client in Google Cloud Console with
redirect URI `http://localhost:8000/auth/callback`, downloaded as `credentials.json`):
```bash
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
python -m uvicorn app:app --reload
```

Run the directory-access CLI check (needs a Desktop-app-type OAuth client, separate
`credentials.json` from the web app's):
```bash
python src/check_directory_access.py
```

(Legacy PDF indexers and figure extractors are archived in `Archive DO NOT Refer/`.)

## Workflow
- TDD, strictly: failing test → minimum code to pass → refactor. Never weaken or delete an
  existing test to make a build pass.
- Always outline a step-by-step plan before making multi-file modifications.
- Fan out subagents for independent, context-heavy work (e.g. research, log searching, one
  agent per code section being changed).

## Code standards
- Clean Architecture + SOLID: keep domain/business logic (fuzzy matching, PDF structural
  classification) free of HTTP, OAuth, file I/O, and PDF-library specifics. Inject
  dependencies through small, role-specific interfaces rather than instantiating concrete
  classes inline.
- Functions ≤20 executable lines, cyclomatic complexity ≤6, nesting ≤2 levels. Guard clauses
  and early returns over nested `if/else`.
- Intent-revealing names. No speculative abstractions, unused wrappers, or phantom layers.
- Tests cover boundaries, empty/null, and expected exceptions — not just happy paths.

## Definition of done
Run these and fix everything they report before calling a task complete:

1. `ruff check --fix . && ruff format .`
2. `radon cc -s -n B .` — refactor anything graded C or worse
3. `vulture .`
4. `pytest --cov=.` — all green, new branches covered

Wired up via `pyproject.toml` (ruff config, pytest config with a `slow` marker for the
real-1685-page-PDF integration tests) and the `tests/` suite, scoped to the new work —
`src/mo_toc/`, `src/build_mo_toc.py`, `src/serve_mo_toc.py`, `src/web_toc/`,
`src/build_web_toc.py`, `src/build_web_pages.py`, `src/shared/`, and `tests/` (including
`tests/js/`, the viewer's pure JS helpers, run by `node --test` from `tests/test_viewer_js.py`)
— not the whole
repo: `app.py`, `src/check_directory_access.py`, and `Archive DO NOT Refer/` are legacy/
archived and intentionally exempt from this checklist. Apply the checklist to any of those
only if/when they're actually touched, not retroactively.

## Verification commands (quiet flags)
- Python: `pytest -q`

## New code or enhancements
- This is a git repo now. Create a new git worktree for any source code change (use skill
  `superpowers:using-git-worktrees` to manage work in the worktree), open a PR to merge back
  to main, then delete the worktree, local branch, and remote branch after merge
  (`git branch -d <branch-name>` and `git push origin --delete <branch-name>`). This is
  exactly the workflow the `mo_toc` viewer work used.

## Working notes
- A real test suite (664 tests — 646 by default plus 18 `slow` — `pytest -q`) now covers `src/mo_toc/`, `src/build_mo_toc.py`,
  and `src/serve_mo_toc.py` — this is a git repo now too. The OLD exploratory scripts
  (`app.py`, `src/check_directory_access.py`) predate that and were built as ad hoc work,
  verified by direct execution (`py_compile`, sample runs on page/data subsets before a full
  run) rather than automated tests; they're now archived-equivalent in spirit even though
  `app.py` and `check_directory_access.py` themselves still live at their original paths.
  The Workflow/Code standards/Definition of done above are the bar for new work going
  forward; they don't retroactively apply to what's already there unless it's being touched
  anyway.
- Prefer testing a small sample first for anything that processes the full 1685-page PDF or
  the full Workspace directory, before running it against the whole thing.
