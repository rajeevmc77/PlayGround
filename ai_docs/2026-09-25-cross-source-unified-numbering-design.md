# Cross-source unified numbering — design

Date: 2026-09-25
Supersedes the numbering rules (not the field) of `2026-09-21-unified-numbering-design.md`.

## Goal

Every node in `output/bcbc_pdf.json` and `output/bcbc_web.json` carries a
`unified_number` that is **the same string in both files for the same piece of
the code**, so the two extracts can be compared key-by-key. Covered levels:
volume, division, part, section, subsection, article, sentence, clause,
subclause, Notes to Part, Note, table, row, cell (column) and image.

## Why the current numbers don't line up

Today's `shared/numbering.py` numbers every level by its position among
same-type siblings. Measured on the current outputs (2026-09-25):

| Level | PDF | Web | Same key |
|---|---|---|---|
| Part | 15 | 15 | 14 |
| Section | 99 | 100 | 61 |
| Article | 1997 | 2022 | 951 |
| Sentence | 5157 | 5194 | 2486 |
| Table | 286 | 333 | 51 |
| Row / Cell | 15.5k / 59k | 15.2k / 49k | 0 |
| Image | 627 | 326 | no key at all |

Root causes:
1. **Volumes differ.** The web puts Division B Part 9 in Volume 2 (`2.B.1`)
   and so numbers Part 10 as `1.B.9`; the PDF is one volume (`1.B.9`, `1.B.10`).
2. **Positional drift.** One missing or extra sibling shifts every later one;
   the web's "Preface" division has an empty identifier (`1..3`).
3. **Spelling.** PDF `Row1.Col1` vs web `row1.col1`.
4. **Table parents.** The PDF hangs a table off its Sentence, the web off its Article.
5. **Images** have no `unified_number` in either file.
6. **Notes** exist only in the PDF (`NotesContainer` → `Note`); the web stops at
   `part_appendix`, although the site's `appendix.json` does carry each
   `application_note` with its official `number`.

## Key scheme

Keys come from the code's **own numbering**. Identifiers are normalised
(trailing `.` stripped, `row`/`Row` → `Row`, `col`/`Col` → `Col`). Position
is used only where no official number exists. **Volume is not part of any
descendant's key.**

| Level | Rule | Example |
|---|---|---|
| Volume | `V` + number | `V1`, `V2` |
| Division | letter | `B` |
| Part / Section / Subsection / Article | division + official number (absolute) | `B.9`, `B.9.10`, `B.9.10.18`, `B.9.10.18.2` |
| Sentence | article + `.` + label | `B.9.10.18.2.(2)` |
| Clause / Subclause | label appended directly | `B.9.10.18.2.(2)(a)(i)` |
| Notes to Part | part + `.Notes` | `A.1.Notes` |
| Note | division + `.A-` + official note number | `A.A-1.1.1.1.(3)` |
| Division appendix (C, D) | `App` + letter | `AppD` |
| Appendix sub-levels | appendix + official number | `AppD.D-2.11.3` |
| Table | owning **article / note / appendix-level** key + `.Tbl` + ordinal | `B.9.10.18.2.Tbl1` |
| Row / Cell | `.Row` n / `.Col` n | `B.9.10.18.2.Tbl1.Row3.Col2` |
| Image | owning article/note key + `.Fig` + ordinal (non-decorative only) | `A.A-1.1.1.1.(6).Fig1` |
| Front matter / Preface, index, conversions, spectables, back matter | `FM`/`BM`/`Idx`/`Conv`/`Spec` + ordinal | `FM.3` |

Rules:
- **Table ordinal** counts tables within the owning article/note in document
  order, independent of where the table sits in the tree (the PDF keeps it
  under its Sentence).
- **Image ordinal** counts non-decorative images within the owning
  article/note in document order. PDF `owner_citation` (often clause-level) is
  walked up to its article/note. Images are a flat list; each image entry gets
  a `unified_number` field.
- **Duplicates**: if a file produces the same key twice, the later one gets a
  `~2` (`~3`, …) suffix so keys stay unique within a file.
- Front matter / Preface keys are unique but **not** expected to match.

Known limitation: the PDF sometimes rasterises one figure as several images
(627 vs 326), so `.Fig` keys match less reliably than text levels.

## Headings

Both files gain a `heading` field on heading nodes holding the literal heading
text; `title` stays the descriptive name.

| Node | `heading` | `title` |
|---|---|---|
| Division | `Division A` | `Compliance, Objectives and Functional Statements` |
| Part | `Part 1` | `Compliance` |
| Section | `Section 9.10.` / `9.10` | `Fire Protection` |
| Notes to Part | `Notes to Part 1` | `Notes to Part 1` (both files) |
| Note | `A-1.1.1.1.(3)` | `Factory-Constructed Buildings.` |

- **Notes to Part title**: in both files the Notes-to-Part node's `title` is
  exactly `Notes to Part N`, matching the website's own heading. Today the PDF
  stores the next heading line (the Part's name, e.g. `Compliance`) as the
  title and discards `Notes to Part 1`; that repeated Part name is dropped,
  since the parent Part already carries it. Its `unified_number` is
  `<division>.<part>.Notes` in both files — e.g. PDF `Notes-A-1` and web
  `nbc.divA.part1.appendix` both become `A.1.Notes` (web Volume 2 Part 9's
  `nbc.divBV2.part9.appendix` becomes `B.9.Notes`, same as PDF `Notes-B-9`).
- PDF: `heading` is the trigger line the heading regex already matches (e.g.
  `RE_NOTES_CONTAINER` in `mo_toc/parsing/heading_rules.py`), which is currently discarded.
- Web: split from the nav title — `"Part 1 - Compliance"` → heading `Part 1`,
  title `Compliance`; `"Notes to Part 1"` → heading `Notes to Part 1`.

## Notes placement

Each "Notes to Part N" is placed **under Part N of the same division**, as the
Part's last child after its Sections — the website's own layout.

- **PDF**: `NotesContainer` is currently a sibling of the Parts under the
  Division. After the tree is built, a re-parenting step moves each container
  into the Part with the same division and number. Verified against the
  current output: all 12 containers (A-1, A-2, A-3, B-1, B-3, B-4, B-5, B-6,
  B-8, B-9, B-10, C-2) have a matching Part. A container with no matching
  Part is an error (the build fails loudly rather than guessing).
- **Web**: `part_appendix` is already a child of its Part (all 12, including
  `nbc.divB.part10.sect4.appendix` under Part 10 and
  `nbc.divBV2.part9.appendix` under Volume 2 Part 9). New `Note` nodes are
  built from each `application_note` in the already-fetched `appendix.json`
  (`number`, `title`, paragraph/list text) and attached under their
  `part_appendix`. Tables and figures whose id lies under an `appnoteX`
  attach to / are owned by that Note.

## Components

- `src/shared/numbering.py` — replace the positional algorithm with a
  rule-driven one. Each pipeline supplies a per-type rule table:
  `absolute` (division + official number), `child` (parent + `.` + segment),
  `suffix` (parent + identifier), `ordinal` (parent + prefix + count),
  `fixed` (`V1`, `B`, `AppD`, `.Notes`). Shared identifier normalisers and the
  duplicate guard live here. Still duck-typed on
  `.type/.children/.identifier/.unified_number`. A separate
  `number_images(images, owner_key_of)` assigns image keys.
- `src/mo_toc/` — record `heading`; re-parent `NotesContainer`s; table ordinal
  by owning article/note; image keys from `owner_citation`; new rule table in
  `parsing/numbering_config.py`.
- `src/web_toc/` — Note extraction from `application_note`; attach appnote
  tables/figures to their Note; `heading`/`title` split; new rule table.
- `src/compare_unified.py` (new CLI) — loads both JSONs and prints, per level,
  keys in both / PDF-only / web-only; `--diff` also lists matched keys whose
  normalised text differs.
- Viewer — no code change expected; it already shows `unified_number`. The
  PDF tab now shows Notes inside each Part.

## Testing

TDD throughout:
- Each rule and normaliser, including empty identifier (web Preface),
  trailing dots, unknown type, duplicates (`~2`).
- Notes re-parenting: normal case, Part with no Notes, container with no
  matching Part (raises).
- Notes-to-Part node: title is `Notes to Part N` in both pipelines and
  unified_number is `<division>.<part>.Notes` (incl. web Volume 2 Part 9 → `B.9.Notes`).
  The full-rebuild compare report must show all 12 `Notes` keys in both files
  with identical titles.
- Web Note extraction from an `application_note` fixture; appnote table/figure ownership.
- Image keys: clause-level owner walked up to article; decorative skipped; ordinals.
- Cross-source fixture: a small PDF-shaped tree and web-shaped tree for the
  same article produce identical keys.
- `compare_unified.py` on fixtures.
- Full rebuild of both JSONs, then the compare report. Target: near-100%
  agreement on Part→Article (from ~48% today); residual gaps are listed as
  genuine parse differences.

Definition of done per CLAUDE.md (ruff, radon ≤ B, vulture, pytest --cov).

## Out of scope

- Pixel/phash image matching.
- Making front matter / Preface / back matter keys match across sources.
