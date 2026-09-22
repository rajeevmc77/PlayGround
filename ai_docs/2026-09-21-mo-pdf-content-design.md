# `mo_pdf.json` design: full-content extraction for the MO Package index

## Motivation and rename

Today's `output/mo_toc.json` is a *structural* index — every node knows its page,
bounding box, and (for headings) its title, but the actual body text of an
Article's Sentences/Clauses/Subclauses is truncated to one physical PDF line,
tables are entirely absent from the tree (their caption is indexed, their rows
are not), and figures/tables render as a flat, loosely-owned side list rather
than living where they're discussed. This design closes those gaps: every leaf
node carries its complete text, tables become first-class structured entities
with per-row/per-cell boundaries, and images attach at the most precise node
that owns them — down to a Sentence/Clause/Subclause when that's genuinely
where they belong.

Because the output is no longer a table-of-contents skeleton but a full parse
of the PDF's content, the artifact is renamed **`mo_toc.json` → `mo_pdf.json`**.
This rename is scoped to the output filename only — `src/mo_toc/` as a
package, its class names, and its CLI entry points keep their existing names;
renaming those is a separate, much larger exercise this spec doesn't take on.

Files touched by the rename: `src/build_mo_toc.py` (write target), the
default `toc_json_path` in `src/mo_toc/web/api.py`, and `CLAUDE.md`'s
documentation of the output filename.

## Confirmed bugs this design fixes

Verified against the real output (`output/mo_toc.json`, built from the real
1685-page PDF), not hypothetically:

1. **Text truncation.** `body_segmenter.py` only ever keeps a marker line's
   *first physical line*; every wrapped continuation line is silently
   dropped. Confirmed on Clause `A-1.1.1.1.(1)(k)`: current output reads
   `"...installation, replacement, or"` — cut off mid-sentence, missing
   `"alteration of materials or equipment regulated by this Code,"`, which
   sits on the very next PDF line.
2. **Tables are invisible as content.** `_open_caption` records a Table's
   caption title only; every subsequent row/cell line falls through into
   whatever Article's body accumulator is open, and disappears into bug #1.
3. **Tables are misclassified as images.** `vector_cluster.cluster_drawing_rects`
   merges a table's border rects into one large bbox, which clears the
   400pt² diagram-area threshold and gets rendered and indexed as a figure.
   Confirmed: page 8's `Table 1.1.1.1.(5)` is currently emitted as
   `images/img_3.png`, matched to the Table caption as if it were a figure
   snapshot.
4. **Two dormant fields.** `Caption.forming_part_of` and `Caption.continuation`
   exist in the domain model but are hardcoded to `None`/`False` and never
   populated — evidently intended for exactly the table/multi-page problem
   this design solves, never finished.
5. **Image ownership is deliberately floored above Sentence/Clause/Subclause**
   (`image_matcher.py`'s `_NON_OWNER_TYPES`), even though this doc's own
   Table work proves finer attachment is both meaningful and achievable.

## Schema changes

### `Node` (domain/models.py)

Add one field:

```python
@dataclass
class Node:
    type: str
    identifier: str
    citation: str
    title: str
    content: str = ""          # NEW
    page: int
    end_page: int
    bbox: BBox
    children: list["Node"] = field(default_factory=list)
    unified_number: str = ""
```

No new dataclass is introduced for Table/Row/Cell — they reuse `Node`,
matching how Sentence/Clause/Subclause already do.

### `title` vs `content` vs neither, by type

| Type | Field populated | Notes |
|---|---|---|
| Volume, FrontMatter, Division, Part, NotesContainer, Section, Subsection, Article, Note, Appendix, AppendixPart, AppendixSection, AppendixArticle, TableGroup, BackMatter | `title` | Unchanged from today. |
| **Table** | `title` | Its caption's descriptive title (e.g. `"Alternate Compliance Methods for Heritage Buildings"`) — structurally like an Article's title, not body text. |
| **Row** | *(neither)* | Purely structural; no heading text of its own. |
| Sentence, Clause, Subclause, **Cell** | `content` | Full, multi-line, marker-stripped text. |

`json_writer.py` prunes the unused key per node after `dataclasses.asdict()`:
drop `content` for every type except `{Sentence, Clause, Subclause, Cell}`;
drop `title` for `{Sentence, Clause, Subclause, Cell, Row}`. A pruned key is
**absent** from the JSON, not present as `""`.

### New node types: Table → Row → Cell

Mirrors the existing Sentence → Clause → Subclause pattern:

- **Table**: `citation = f"Table:{caption.identifier}"` (mirrors the existing
  `Note:{identifier}` convention already in the codebase), `bbox` = the
  table's outer grid boundary, `page`/`end_page` span every page its rows
  land on, `children` = `Row` nodes.
- **Row**: `identifier` = positional (`Row1`, `Row2`, ...) — not derived from
  a table's own "No." column, since most tables in this document don't have
  one. `bbox` = that row's boundary from the horizontal gridlines.
  `citation = f"{table.citation}-Row{n}"`.
- **Cell**: `identifier` = positional (`Col1`, `Col2`, ...). `bbox` = that
  cell's boundary from the grid intersection. `content` = its own text,
  joined from every physical line inside the cell, in reading order.
  `citation = f"{row.citation}-Col{n}"`.

A table's header row is modeled as an ordinary `Row1` whose cells hold the
header labels (`"No."`, `"Code Requirement in Division B"`, ...) — no
separate `is_header` flag. `Table`/`Row`/`Cell` bypass the heading rank/stack
mechanism entirely (no `RANK` entry) — they're attached directly via
`parent.children.append(...)`, not opened through `_open_node`.

`unified_number` is extended to cover Table/Row/Cell via
`src/shared/`'s numbering algorithm, for consistency with every other node
type.

### `ImageAsset` (domain/models.py)

Add one field:

```python
@dataclass
class ImageAsset:
    ...
    title: str = ""   # NEW: f"{caption_kind} {caption_identifier}" when matched, else ""
```

Example: `"title": "Figure A-1.1.1.1.(6)"`. `caption_kind`/`caption_identifier`/
`caption_title` are unchanged and stay alongside it (they already carry
useful, distinct information — kind/identifier for addressing, `caption_title`
for the descriptive text, `title` as the ready-to-display combined label).

## Parsing changes

### 1. Sentence/Clause/Subclause: capture full content

`body_segmenter.py`'s `_add_markers_to_sentence` is restructured from
"extract only marker lines" into a single forward pass that tracks a
**current owner** pointer:

- Starts as the sentence itself once its own first line is consumed
  (`content = match.group(2)`, the marker-stripped text already captured by
  the existing `RE_MARKER` regex — today this text is discarded in favor of
  the raw `pline.text` with the marker still attached; the fix simply uses
  the group already being computed).
- A clause-marker line creates a new Clause node, appends it to the
  sentence's children, and becomes the new current owner (also tracked
  separately as "current clause" for subclause parenting).
- A subclause-marker line creates a new Subclause node under the current
  clause, and becomes the new current owner.
- Any other line (no marker match) is a continuation line: its text is
  space-joined onto the current owner's `content`, and — only if it's on the
  **same page** as the owner's own first line — its bbox is unioned into the
  owner's bbox (same technique `_caption_block_bbox` already uses for
  captions). A bbox describes one page's rectangle; `end_page` already
  carries the fact that content can span pages, so a continuation line on a
  later page extends `content` and `end_page` but not `bbox`.

The existing ambiguity-resolution logic (`_resolve_kind`, the clause/subclause
x0 threshold, the `next_letter` roman-numeral sequencing) is untouched — it
only ever inspected marker lines, which are unaffected by this change.

**Table-region lines are excluded from this pass entirely** (see next
section) — they never reach `_append_to_current_article` in the first place,
so they can't be misattributed as continuation text.

### 2. Table extraction (new module, `src/mo_toc/parsing/table_extractor.py`)

**Anchored, not blind.** Detection starts from a `Table`/`Figure`-kind
caption line — already reliably found today (492 hits via
`classify_caption_line`) — rather than scanning every page for grid-shaped
vector rects, which risks false positives on ordinary boxes/borders.

1. From a Table caption's position, search `page_drawing_rects()` below it
   for a grid: separate rects into "horizontal" (wide, thin height) and
   "vertical" (tall, thin width); horizontal rects' y-midpoints become row
   boundaries, vertical rects' x-midpoints become column boundaries.
   Confirmed on the real PDF: `Table 1.1.1.1.(5)` (page 8) yields 71 drawing
   rects forming an exact 3-column grid with row dividers at every row
   boundary — the geometry is precise, not approximate.
2. Every non-caption `PageLine` whose bbox center falls inside the table's
   outer bbox is assigned to the (row-band, column-band) cell containing it;
   same-cell lines are joined in y-order into that cell's `content`.
3. **Owner resolution** ("Forming Part of X"), tried in priority order:
   1. The caption's own `identifier`, treated as a citation and looked up
      directly against existing node citations (e.g. `Table 1.1.1.1.(5)`'s
      identifier `"1.1.1.1.(5)"`, prefixed with the current division letter,
      exactly matches Sentence `A-1.1.1.1.(5)`'s own citation).
   2. A `Forming part of <Sentence|Clause|Article|...> X` line, parsed
      directly. Newly discovered: this line renders in **regular** (non-bold)
      font, so it's currently invisible to `_consume_caption_title`'s
      bold-only gate and silently dropped today — same root bug as #1 above.
      It's consumed as its own line (not folded into the caption title) and
      used only when strategy (1) doesn't resolve.
   3. Fallback: the nearest enclosing structural node (today's
      `owner_citation` behavior), for the rare caption with neither a
      citation-shaped identifier nor a parseable "Forming Part of" line.
4. **Multi-page continuation**: if a table's grid lacks a closing bottom
   border on the page it starts on, and the following page opens with a
   matching grid in the same x-range with no new Table caption (matching the
   observed pattern of blank-titled continuation captions, e.g.
   `3.2.3.1.-C`), its rows are appended as further `Row` children of the
   *same* `Table` node rather than creating a second one — `end_page` extends
   accordingly. This heuristic can't be fully de-risked by design alone; it
   needs validation against more real multi-page tables during
   implementation.
5. Consumed lines are recorded per page and threaded into `tree_builder.py`'s
   per-page walk as a skip-set, computed once before the line-by-line loop —
   so they never reach `_append_to_current_article`.

### 3. Image pipeline: stop misclassifying table borders as figures

The same per-page table bboxes computed in step 2 above are passed into
`image_extractor.vector_images_on_page`'s existing `exclude_overlapping_rects`
call, the same mechanism already used to exclude raster-image bboxes from
vector-cluster candidates. No screenshot is produced for a table at all —
its structured Row/Cell content replaces the need for one. This requires
table-region bboxes to be available before/alongside image extraction; both
now consume the same per-page pre-pass output (threaded through
`parallel_extraction.py`'s per-worker per-page results, alongside raster
images and body lines).

### 4. Image ownership: descend as granular as possible

`image_matcher.py`'s `_NON_OWNER_TYPES` (currently `{Sentence, Clause,
Subclause}`) is removed. `_best_child`'s existing position-based walk
(nearest preceding sibling by `(page, y0)`) already generalizes correctly to
these types once they're no longer filtered out — and this design's Sentence/
Clause/Subclause bbox fix (§1) makes their positions more precise inputs to
that same walk. No new resolution algorithm is needed; this is a filter
removal, not new logic. `Table`/`Row`/`Cell` are added to `_NON_OWNER_TYPES`
instead — an image is never attributed to a specific table cell.

This explicitly includes small inline images — e.g. formula/equation
graphics embedded within a Clause or Subclause's own text — not just
page-sized figures. `assign_owner` already runs unconditionally for every
image regardless of size (the 40pt `MIN_CAPTION_ELIGIBLE_DIM` floor only
gates *caption claiming*, i.e. whether an image gets a `Figure X` label — it
was already separate from ownership resolution, so this requirement is
satisfied by the filter removal above with no further change needed). A
formula image sitting inside Clause `A-1.1.1.1.(1)(k)`'s own text, for
example, resolves to that Clause as owner, not to the enclosing Article.

Accepted risk, not mitigated: an image positioned ambiguously between two
Clauses on the same page (after one's last line, before the next one's
first) resolves to whichever is "most recently opened" per existing
position-walk semantics — the same ambiguity the walk already accepts at
Article/Note granularity today, now just exercised at the finest level.

## Example: updated schema shape

Article `1.1.1.1.` today (abbreviated), showing the new shape:

```json
{
  "type": "Article",
  "identifier": "1.1.1.1.",
  "citation": "A-1.1.1.1.",
  "title": "Application of this Code",
  "page": 7, "end_page": 12, "bbox": { "...": "..." },
  "children": [
    {
      "type": "Sentence",
      "identifier": "(1)",
      "citation": "A-1.1.1.1.(1)",
      "content": "This Code applies to any one or more of the following:",
      "page": 7, "end_page": 7, "bbox": { "...": "..." },
      "children": [
        {
          "type": "Clause",
          "identifier": "(k)",
          "citation": "A-1.1.1.1.(1)(k)",
          "content": "except as permitted by the British Columbia Fire Code, the installation, replacement, or alteration of materials or equipment regulated by this Code,",
          "page": 7, "end_page": 7, "bbox": { "...": "spans both physical lines" },
          "children": [],
          "unified_number": "1.A.1.1.1.1.(1)(k)"
        }
      ]
    },
    {
      "type": "Sentence",
      "identifier": "(5)",
      "citation": "A-1.1.1.1.(5)",
      "content": "For heritage buildings, the Alternate Compliance Methods for Heritage Buildings in Table 1.1.1.1.(5) may be substituted for requirements contained elsewhere in this Code. (See Note A-1.1.1.1.(5).)",
      "page": 8, "end_page": 8, "bbox": { "...": "..." },
      "children": [
        {
          "type": "Table",
          "identifier": "1.1.1.1.(5)",
          "citation": "Table:1.1.1.1.(5)",
          "title": "Alternate Compliance Methods for Heritage Buildings",
          "page": 8, "end_page": 8, "bbox": { "...": "outer grid boundary" },
          "children": [
            {
              "type": "Row", "identifier": "Row1", "citation": "Table:1.1.1.1.(5)-Row1",
              "page": 8, "end_page": 8, "bbox": { "...": "row boundary" },
              "children": [
                { "type": "Cell", "identifier": "Col1", "citation": "Table:1.1.1.1.(5)-Row1-Col1", "content": "1", "page": 8, "end_page": 8, "bbox": {} },
                { "type": "Cell", "identifier": "Col2", "citation": "Table:1.1.1.1.(5)-Row1-Col2", "content": "Fire Separations Sentence 3.1.3.1.(1), Table 3.1.3.1., Subsection 9.10.9. 2 h fire separation required between some major occupancies.", "page": 8, "end_page": 8, "bbox": {} },
                { "type": "Cell", "identifier": "Col3", "citation": "Table:1.1.1.1.(5)-Row1-Col3", "content": "Except for F1 occupancies, 1 h fire separation is acceptable, provided the building is sprinklered.", "page": 8, "end_page": 8, "bbox": {} }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

`images` entries gain `title`:

```json
{
  "page": 33,
  "bbox": { "...": "..." },
  "image_path": "images/img_10.png",
  "owner_citation": "Note:A-1.1.1.1.(6)",
  "caption_kind": "Figure",
  "caption_identifier": "A-1.1.1.1.(6)",
  "caption_title": "Application of Alternative Compliance Methods in Table 1.1.1.1.(6)",
  "title": "Figure A-1.1.1.1.(6)"
}
```

## Out of scope for this pass

- **Merged/spanning cells** (rowspan/colspan). Not present in the sample
  table; v1 assumes a uniform grid. Flagged as a known simplification, not
  silently mishandled — a spanning cell would currently be assigned to
  whichever single grid cell its bbox center falls in.
- **Deeper image-ownership disambiguation** beyond the existing
  nearest-preceding-sibling walk (see accepted risk above).
- **Renaming `src/mo_toc/` itself**, its classes, or CLI entry points beyond
  the output artifact's filename.
- **Two confirmed, deliberately-unfixed table-content gaps found during
  real-PDF validation (Task 14)**, both accepted as leaks (visible, in body
  text) rather than risking silent misattribution under a wrong table
  citation:
  - Table `1.1.1.1.(5)`'s last ~4 rows (of 37) share page 12 with the next
    table's own caption, with no geometric or font signal distinguishing
    them from ordinary body prose in between — a heuristic built for this
    case was found to silently misfile unrelated sentence prose as fake
    table rows and was reverted.
  - Document-wide, roughly 22-30 pages carry a table caption whose grid
    never fit on that page (an "orphaned anchor") or a top-of-page grid
    with no preceding table to continue — this table content is currently
    captured nowhere (leaks as body text, same as before this feature),
    rather than being guessed at and risking a wrong attribution. This is
    broader than just the Table `1.1.1.1.(5)` case above; a real fix would
    need to detect and index these tables as their own new anchors, not a
    continuation-detection concern.

## Files affected

- `src/mo_toc/domain/models.py` — `Node.content`, `ImageAsset.title`.
- `src/mo_toc/parsing/body_segmenter.py` — full-content capture rewrite.
- `src/mo_toc/parsing/tree_builder.py` — table skip-set threading, Table/Row/
  Cell attachment, `Forming part of` line consumption.
- `src/mo_toc/parsing/table_extractor.py` — **new**: grid detection, row/
  column boundary derivation, cell assignment, continuation detection.
- `src/mo_toc/parsing/image_extractor.py` — exclude table bboxes from vector
  clusters.
- `src/mo_toc/parsing/image_matcher.py` — remove Sentence/Clause/Subclause
  from `_NON_OWNER_TYPES`, add Table/Row/Cell, add `title` formatting.
- `src/mo_toc/parsing/parallel_extraction.py` — thread table-region output
  per page alongside existing raster/body-line results.
- `src/mo_toc/output/json_writer.py` — title/content pruning per type.
- `src/shared/` (numbering) — extend to Table/Row/Cell.
- `src/build_mo_toc.py` — write to `mo_pdf.json`.
- `src/mo_toc/web/api.py` — read `mo_pdf.json`.
- `src/mo_toc/web/static/viewer.js` — `formatNodeLabel` fallback to `content`
  when `title` is absent; render Table/Row/Cell nodes without breaking.
- `CLAUDE.md` — update the documented output filename.

## Testing plan

Per this repo's strict TDD rule (update, never weaken, existing tests):

- New `tests/test_table_extractor.py`: grid clustering into row/column
  boundaries, cell text assignment and multi-line joining, single-page and
  synthetic multi-page continuation, owner resolution (citation-match,
  `Forming part of` line, fallback), exclusion from image vector clusters.
- `tests/test_body_segmenter.py`: continuation-line joining, marker
  stripping, same-page bbox union, cross-page content without bbox
  extension.
- `tests/test_tree_builder.py`: Table/Row/Cell attachment as children,
  table-region line exclusion from Article body.
- `tests/test_domain_models.py`: `Node.content` / `ImageAsset.title`
  construction.
- `tests/test_json_writer.py`: title/content pruning per type, round-trip.
- `tests/test_image_matcher.py`: Sentence/Clause/Subclause ownership descent,
  Table/Row/Cell exclusion from ownership.
- `tests/test_api.py`, `tests/test_serve_mo_toc.py`: fixtures updated for the
  new schema and the `mo_pdf.json` filename.
- `tests/test_mo_toc_numbering_config.py`,
  `tests/test_mo_toc_numbering_integration.py`: Table/Row/Cell numbering.
- `tests/test_integration_real_pdf.py` (slow-marked): full real-PDF run,
  spot-checking the specific examples verified in this document (Clause
  `A-1.1.1.1.(1)(k)`'s full text, Table `1.1.1.1.(5)`'s row/cell structure,
  Figure `A-1.1.1.1.(6)`'s `title`).
