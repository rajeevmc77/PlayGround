# Specification: `src/bcbc_mo_index.py` index generation

Describes what the indexer actually does, node by node, so the JSON/Markdown output can be
interpreted (or the algorithm re-implemented) without reading the source. Reflects the code
as of this writing — see [`src/bcbc_mo_index.py`](../src/bcbc_mo_index.py) for the
authoritative implementation.

## 1. Purpose and inputs

Parses `MO Package BCBC MRK signed.pdf` — a 1685-page PDF merging the BC Building Code with
a Ministerial Order package — into a hierarchical structural index, plus a flat Table/Figure
index. The document's own PDF bookmark outline reflects the source files that were merged to
produce it (e.g. `"04 2023-10-26_NBC2020p1 Division B Part 1.FIN"`), not the Volume →
Division → ... → Article structure, so it cannot be used directly. Instead, headings are
recognized from page text + font metadata during a single top-to-bottom page walk.

Input: one PDF path (default `data/MO Package BCBC MRK signed.pdf`, overridable as a CLI
argument). Parsing uses PyMuPDF (`pymupdf`/`fitz`), reading each page as `get_text("dict")`
to get per-line text, position (`bbox`), and font name per span.

The document consistently numbers everything as Part.Section.Subsection.Article, with
Sentence/Clause/Subclause as bracketed suffixes below Article level — e.g. `3.5.2.1.` is
Part 3 → Section 3.5. → Subsection 3.5.2. → Article 3.5.2.1., and `3.5.2.1.(2)(a)(i)` is that
Article's Sentence (2), Clause (a), Subclause (i). Section/Subsection/Article detection
(§3) already keys off exactly this — the count of dot-separated numbers in the heading text,
not a keyword — so it holds regardless of how a given Section's title happens to be laid
out on the page. Two Appendices (C and D) use a separate, letter-prefixed numbering scheme —
see §6.

## 2. Target hierarchy

```
Volume                              (synthetic root, 1 per document)
  Division                          (A, B, C, ...)
    Part                            (numbered)
      Section                       (N.N)
        Subsection                 (N.N.N)
          Article                  (N.N.N.N)
            Sentence               ((1), (2), ...)
              Clause               ((a), (b), ...)
                Subclause          ((i), (ii), ...)
    NotesContainer  "Notes to Part N"   (sibling of Section, under the same Division/Part)
      Note                         (identifier like "A-9.8.4.")
  Appendix                         (C, D — sibling of Division, under Volume; see §6)
    AppendixPart                   ("Section D-1", no trailing dot)
      AppendixSection              (D-N.N.)
        AppendixArticle            (D-N.N.N. — Sentence/Clause/Subclause live here, same as Article)
  TableGroup                       (Part 9's own "Fire and Sound Resistance Tables" /
                                     "Span Tables" dividers — sibling of Section, under Part; see §3)
```

There is no literal "Volume" heading anywhere in the source text (confirmed by a full-text
scan) — the whole package is treated as a single synthetic Volume node spanning every page,
to match the schema requested, not because the PDF marks one.

Tables and Figures are captured as a separate flat list, not nested in the tree — but each
entry now also carries an `owner_citation` (§4), so the association with the enclosing
Article/Note/AppendixArticle is recorded even though it isn't a child in the tree.

## 3. Heading detection (Division … Subsection)

A text line is treated as a heading candidate only if:

1. Its rendered font name contains `"Black"` (i.e. `Arial-Black` in this PDF), **and**
2. The bare line text matches one of these patterns (checked in this order):

| Type | Regex | Example match |
|---|---|---|
| Division | `^Division\s+([A-Z])\s*$` | `Division B` |
| NotesContainer | `^Notes to Part\s+(\d+)\s*$` | `Notes to Part 9` |
| Part | `^Part\s+(\d+)\s*$` | `Part 9` |
| Section | `^Section\s+(\d+\.\d+)\.\s*(.*)$` | `Section 9.10. Fire Protection...` |
| Article | `^(\d+\.\d+\.\d+\.\d+)\.\s+(.*)$` | `9.10.14.1. Nature of...` |
| Subsection | `^(\d+\.\d+\.\d+)\.\s+(.*)$` | `9.10.14. Fire...` |
| Appendix | `^Appendix\s+([A-Z])\s*$` | `Appendix D` |
| AppendixPart | `^Section\s+([A-Z])-(\d+)\s+(.*)$` | `Section  D-1  General` |
| AppendixArticle | `^([A-Z])-(\d+\.\d+\.\d+)\.\s+(.*)$` | `D-1.1.1. Scope` |
| AppendixSection | `^([A-Z])-(\d+\.\d+)\.\s+(.*)$` | `D-1.1. Introduction` |
| TableGroup | `^[A-Z][A-Za-z ]*\bTables\s*$` | `Fire and Sound Resistance Tables` |

Article (4-part numbers) is checked before Subsection (3-part numbers) in the pattern list,
even though a 3-part regex could never actually match a 4-part heading here (after the
mandatory trailing dot the regex requires whitespace, but a 4-part number has another digit
there instead) — the explicit order just keeps the intent readable. Same reasoning for
AppendixArticle before AppendixSection.

The Article pattern's separator is `\.\s*` (zero or more spaces), not `\.\s+` like every
other numbered pattern — confirmed two Articles in the source PDF text extraction have no
space at all between the number and the title (`3.2.2.64.Group D, up to 2 Storeys`,
`3.8.5.7.Adaptable Dwelling Unit Bathrooms`; their own sibling headings on the same page do
have the normal space, so this reads as a PDF-extraction quirk specific to these two lines).
Deliberately **not** relaxed on Subsection too: Article is checked first, so a 4-part number
is always claimed there before Subsection ever sees it — relaxing Subsection's own separator
as well would let its 3-part prefix wrongly swallow the first three segments of an
already-matched-elsewhere 4-part number with nothing to stop it, exactly the false positive
the paragraph above already guards against.

`TableGroup` covers a different, unnumbered kind of heading: Part 9 — by far the largest
Part — ends its own narrative content with two bare divider headings grouping its compiled
tables, `Fire and Sound Resistance Tables` and `Span Tables` (confirmed the only two of their
kind anywhere in the document, and both real: an exhaustive scan of every Arial-Black line
that neither matched a heading pattern nor got folded into a preceding title's continuation
found exactly four unaccounted-for lines total — these two plus the pair of missing-space
Articles above — and zero once both are handled). Left unrecognized, everything from the
first divider to `Notes to Part 9` — Table and Figure captions included — was silently
absorbed as undifferentiated body text of whichever Article happened to be open beforehand:
confirmed that Article's own page length was inflated to 318 pages before this fix (192 after
recognizing the dividers — still large, but that's the genuine size of Part 9's own
"Attributions to Acceptable Solutions" table with no further headings inside it, not a parsing
bug: the same exhaustive scan found nothing else unaccounted-for in that range). Deliberately
narrow — must literally end in the word "Tables" — rather than a general "any orphaned
Arial-Black line is a heading" catch-all, since the exhaustive scan is what established the
pattern's scope is complete against this document, not a guess that a broader rule would need.

**Why the font gate matters:** body text routinely *cites* a heading number mid-sentence
(e.g. `"...as required in Subsection 3.1.3.1. of Division A"`), which would otherwise
false-positive match the Subsection/Article patterns. Body text and citations render in
`BookAntiqua`; only real headings render in `Arial-Black`. Requiring the font match
eliminates this entire class of false positive without needing more complex text heuristics.

**Title continuation across lines and PDF blocks:** a heading's own number+word line and its
title text are not always even the same PyMuPDF layout block — confirmed directly: `Part 1`
and its title `Compliance` render as two separate Arial-Black blocks, and a long title can
wrap onto a further Arial-Black line in yet another block (`Section 1.3. Divisions A, B and
C of this` continues as `Code` in its own block). Because of this, each page's lines are
flattened across *all* of its blocks into one top-to-bottom stream (sorted by `y0`, then
`x0`) before any heading/caption detection runs, rather than processing block-by-block. After
a heading is matched, subsequent lines in that stream are folded into its `title` as long as
they keep the Arial-Black weight and do not themselves match a heading pattern — this is what
recovers `Compliance` as Part 1's title and the missing `Code` suffix on Section 1.3.'s title,
neither of which the (now superseded) per-block version could see. It's also what recovers
`Appendix C`'s full 2-line title, `Climatic and Seismic Information for Building Design in
Canada`.

**One override to "stop at a heading-shaped line":** a continuation line that itself matches
a heading pattern is still folded into the title if the text captured immediately before it
trails off on `and`/`or` (`RE_ENDS_WITH_CONJUNCTION = \b(?:and|or)\s*$`, case-insensitive).
Confirmed real, single instance in the whole document: Division C's Subsection `2.2.9.`'s own
title cross-references another heading by name mid-wrap — `Drawings, Specifications and
Calculations for Subsection 10.2.3. and` / `Section 10.3.` — and without this override,
`Section 10.3.` alone on its own line reads as a genuine new Section: it prematurely closed
the real Subsection and reparented its own Articles (`2.2.9.1.`, `2.2.9.2.`) one level too
shallow, as children of a bogus `Section C-10.3.` node with an empty title instead of
Subsection `C-2.2.9.`'s own children. Found by scanning the whole tree for structural
(non-Division/Appendix/NotesContainer) nodes with an empty `title` — this was the only one.

Rank assigned to each heading type (used to place it in the tree, see §7):

```
Division=1  Part=2  NotesContainer=2  Section=3  Subsection=4  Article=5  Note=6
Appendix=1  AppendixPart=2          AppendixSection=3          AppendixArticle=5
TableGroup=3
```

`ARTICLE_TYPES = ("Article", "AppendixArticle")` names the two types that directly hold
Sentence/Clause/Subclause children (§8) — everywhere the code needs to check "is this an
Article-like node," it checks membership in this pair rather than a single type string.

## 4. Table/Figure caption detection

A line is a caption candidate if it matches `^(Table|Figure)\s+(\S.*)$` **and** its font
contains `"Bold"` but not `"Black"` **and not `"Narrow"`** — i.e. `Arial-BoldMT` (or, in a
couple of appendices, `BookAntiqua-Bold`/`PalatinoLinotype-Bold`), distinct from the
`Arial-Black` used for structural headings and from `ArialNarrow-Bold`, the condensed font
family reserved for a table's own header/data cells. This distinguishes a genuine caption
(e.g. `Table 9.10.14.A`) from a plain-text body mention of the same table/figure number, e.g.
`"Figure A-9.8.4.-B in Note A-9.8.4. of Division B."`, which renders in plain `BookAntiqua`
and is correctly rejected by the font check. The `"Narrow"` exclusion applies to the caption
*trigger* itself, not just to title-continuation (§ below, added there first) — confirmed one
real table's own cross-reference cell, rendered `ArialNarrow-Bold`, read exactly `Table
9.10.3.1.-A` (the same identifier as a genuine caption elsewhere in the document); without
this exclusion on the trigger too, it was misread as a second, spurious caption for that same
table with an empty title, since nothing useful followed it. Found via a systematic pass
looking for duplicate `(type, identifier)` pairs across the whole Table/Figure list — this
was the only cause found; the duplicates it produced are gone after the fix, and no false
duplicates remain (a `Table X` and a `Figure X` legitimately sharing the same number, e.g.
`Table C-1` / `Figure C-1`, are two different things on two independent numbering
sequences — not a bug).

Once a caption line is found, subsequent lines in the page's flattened line stream (§3 — not
just the rest of the same PDF block) are appended to its `title` as long as **all** of these
hold, and stop as soon as any fails:

- bold-but-not-black **and not a "Narrow" font variant** — every caption/title in this
  document renders in `Arial-BoldMT` (or, in a couple of appendices, `BookAntiqua-Bold` /
  `PalatinoLinotype-Bold` — never a Narrow face), while a table's own header/data cells
  consistently render in `ArialNarrow`/`ArialNarrow-Bold`, a distinct condensed font family
  reserved for compact tabular data. This is the single strongest stop condition — confirmed
  directly by inspecting the Division B Part 9 thermal-resistance/insulation tables where
  titles used to leak into the header (e.g. `Table A-9.36.2.8.(1)-C`'s header row `Size, mm,
  and Spacing, mm o.c., of Below-Grade Interior Non-loadbearing Wood-frame` / `Wall Assembly`
  is `ArialNarrow-Bold`, distinct from the title's own `Arial-BoldMT`); adding this one check
  eliminated the leak on every case found, with no observed false positives;
- not itself a new `Table`/`Figure` caption line;
- not a "Forming part of ..." line (§ below) — confirmed this line's own font weight is
  **inconsistent** across the document (sometimes bold, sometimes not), so it's matched on
  text alone and always stops title accumulation, regardless of font;
- not a "Notes to Table/Figure X:" footnote-intro line (`^notes? to (table|figure)\s*`,
  case-insensitive — confirmed recurring, e.g. `Notes to Figure A-3.4.6.4.:`, `Note to Figure
  A-9.3.2.9.(1)-A:`);
- not sharing a `y0` position (rounded to 1pt) with any other line on the page — the
  signature of a multi-column table row (e.g. several bold header cells at the same height,
  confirmed on `Table D-1.1.2.`'s header: `Document Number(2)` / `Title of Document` / `Code
  Reference` all at the same `y0`); a genuine title line never shares its `y0` with anything;
- capped at 3 lines regardless of the above, as a backstop — every confirmed genuine title is
  1–3 lines (confirmed one real title runs the full 3, `Table A-9.11.1.4.-A`: `Options for the
  Design and Construction of Junctions and Flanking Surfaces Between` / `Separating Wall
  Assemblies in Horizontally Adjoining Spaces for Compliance with` / `Clause 9.11.1.1.(1)(b)`).

This captures a caption title that wraps across two or more lines, even when the wrap lands
in a different PDF block (confirmed e.g. `Table A-1.4.1.2.(1)` / `TDGR, WHMIS and British
Columbia Building Code Class Descriptors for Dangerous` / `Goods`, where `Goods` is its own
block), while stopping before the table's own header row or footnotes.

Not fully precise even so: a title's own text can end mid-phrase in the source PDF itself
(confirmed on `Table 4.1.6.2.-B`, whose only title line literally reads `Basic Roof Snow Load
Factor for` before the caption's own `Forming Part of Sentence 4.1.6.2.(2)` line - not a
parsing bug, an accurate transcription of how that specific caption is actually laid out in
the document). And because detection runs per page (§7), a caption that lands at the very
bottom of a page with its title wrapping onto the *next* page picks up no title at all
(confirmed on `Table A-9.11.1.4.-C`, whose caption is the last line on its page) - fixing
that would mean looking ahead across page boundaries, not just PDF blocks, which isn't done
here.

Immediately after the title stops accumulating, the *next* line is tested against
`RE_FORMING_PART = ^forming part of\s+(.+)$` (case-insensitive, any font). A match is stored
verbatim as `forming_part_of` and consumed (so it's never also appended to whatever Article
body happens to be open).

Every entry also gets `owner_citation = citation of the innermost node still open on the
main-walk stack at the moment the caption is seen` — i.e. the enclosing Article's (or
AppendixArticle's) citation, or the enclosing Note's if the caption falls inside a
Notes-to-Part section, or an Appendix/Section/Subsection/Part/Division citation if nothing
deeper is open. This is always available (the stack is never empty below the Volume root) and
is a different, independent signal from `forming_part_of`: `owner_citation` is *where the
caption physically sits in the document*; `forming_part_of`, when present, is what the
document's own text says it belongs to (which can be a specific Sentence one level more
precise than the owning Article, or in principle point elsewhere). No attempt is made to
resolve `forming_part_of` into a specific node reference — it's kept as free text, both
because Sentence-level citations aren't known until segmentation runs in a later pass (§8),
and because it isn't always a single reference (`Forming Part of Sentences 3.1.2.1.(1) and
3.1.2.2.(1)`).

A title ending in `(continued)` (case-insensitive) sets `continuation: true` — confirmed on a
handful of tables that visibly repeat their caption on a later page while spanning more than
one physical page (e.g. `Insulation Materials(6)` / `Insulation Materials(6) (continued)`).
Each continuation is recorded as its own independent flat entry with its own `page`; nothing
merges a table's continuation page(s) back into one combined page range for the original
entry — that would need actual table-grid/layout analysis, out of scope here.

Each entry recorded: `{type: "Table"|"Figure", identifier, title, owner_citation,
forming_part_of, continuation, page}`. These are **not** inserted into the hierarchy tree;
they are collected into two flat lists returned alongside it.

## 5. Notes to Part → Note entries

Note entries (e.g. `A-9.8.4.  Text of the note...`) are never bookmarked and never carry a
distinct heading font — they're plain `BookAntiqua` body text, same as everything else under
a Part. They can only be told apart from ordinary body text by *context*: whether the walk
is currently "inside" a `Notes to Part N` section.

An `in_notes` boolean tracks this context. It is set only when a heading of **rank ≤ 2** is
encountered (Division, Part, NotesContainer, Appendix, or AppendixPart): `True` if the
heading just parsed was a `NotesContainer`, `False` otherwise. Critically, **no other node
type is allowed to touch this flag** — not a Note entry itself, not a rank 3+ heading. This
was a fixed bug: an earlier version reset `in_notes = False` after *every* node creation
including each Note, which meant only the first Note in each container was ever recognized
(12 Notes total instead of the true ~937). Guarding the reset to rank ≤ 2 fixed it.

While `in_notes` is true and a line is not itself a recognized heading, it's tested against
`RE_NOTE_ENTRY = ^([A-Z]-\S+(?:\s+(?:and|to)\s+\(\d+\))*)\s+(.*)$`. A match produces a `Note`
node (rank 6) whose `identifier` is the matched reference (trailing `.` stripped) and whose
`citation` is `Note:{identifier}`.

`RE_NOTE_ENTRY` is loose enough to also match an ordinary capitalized hyphenated word, e.g.
`T-shaped` (`[A-Z]-\S+` matches `T` + `-shaped` just as well as it matches `A-9.8.4.`). This
produced one confirmed false-positive Note in an earlier version, from a Figure's own title
line (`T-shaped wheelchair-turning space`, bold, immediately under its `Figure A-3.8.3.2.(6)`
caption in a different PDF block) that wasn't yet being consumed as the figure's title and so
fell through to the Note check instead. Fixed as a side effect of §4's cross-block caption
title continuation: that line is now consumed into the Figure's `title` before it ever reaches
this check, which is the correct outcome (it isn't a Note) — verified by diffing the Note list
before/after the fix: exactly one entry dropped, `T-shaped`, and nothing else changed.

A second, much larger instance of the same loose-regex risk is §6's Appendix bug — not fixed
by tightening `RE_NOTE_ENTRY` (it can't be, safely; see §10), but by making sure `in_notes` is
reset before Appendix content is ever tested against it in the first place.

One residual, disclosed false positive remains (§10): a body-text *line wrap* that happens to
start with a token shaped like `[A-Z]-\S+` (e.g. `C-B` from a sentence reading `...known as
Schedules A, B, C-A and` / `C-B and located at the end of...`) is indistinguishable from a
real Note's first line using only the signals available here.

## 6. Appendix headings

Two Appendices — C (`Climatic and Seismic Information for Building Design in Canada`) and D
(`Fire-Performance Ratings`) — are inserted after Division B's own `Notes to Part 10` and
before Division C starts. Confirmed by direct inspection of the PDF text. They use a
different, letter-prefixed numbering scheme that none of §3's original patterns recognize at
all: `Appendix D` doesn't match the Division pattern (that requires a bare letter with no
"Appendix" keyword), and `D-1.1.1. Scope` doesn't match the Subsection pattern (that requires
purely-digit segments before the first dot).

**The bug this caused, before the dedicated Appendix patterns existed:** left unrecognized,
`Appendix D` and every heading under it fell straight through to the Note check (§5) while
`in_notes` was still (wrongly) true — carried over from Division B's last real
`Notes to Part 10`, and never reset, because nothing recognized as a rank ≤ 2 heading ever
occurred between it and Division C, ~76 pages later. Confirmed by direct inspection and by
diffing the Note list before/after the fix:

- 133 genuine Appendix C/D headings were mis-tagged as `Note` nodes (e.g. `D-1.1.2. Referenced
  Documents` became a Note with `identifier: "D-1.1.2"`, not a proper structural node) — and
  because Notes don't get body/Sentence segmentation the way Articles do, their own body
  content (which does use the same `1)`/`a)`/`i)` marker convention as the main document) was
  silently dropped instead of being indexed.
- `Notes to Part 10`'s own page range was inflated to wrongly span all of Appendix C and D (it
  showed `length: 76`-ish pages of content it doesn't actually contain, purely because nothing
  else was recognized as a node in between it and the next real heading, `Division C`).
- Every Table/Figure caption inside Appendix C or D got an `owner_citation` pointing at
  whatever real Note last happened to be open before the appendix started (e.g. `Table C-1`
  showed `owner_citation: "Note:A-10.2.3.5.(1)"`, a Division A note with no real connection to
  it) rather than the appendix section it's actually in.

**Fix:** four dedicated patterns (§3) recognized as their own types rather than reusing
Division/Part/Section/Article:

| Type | Pattern | Rank | Citation example |
|---|---|---|---|
| Appendix | `Appendix D` | 1 (same as Division) | `Appendix-D` |
| AppendixPart | `Section  D-1  General` (no trailing dot after the number) | 2 | `Appendix-D-1` |
| AppendixSection | `D-1.1. Introduction` | 3 | `Appendix-D-1.1.` |
| AppendixArticle | `D-1.1.1. Scope` | 5 (same as Article; this is where body content lives) | `Appendix-D-1.1.1.` |

Deliberately **not** reused as `Division`/`Part`/`Section`/`Article`: an Appendix C and a real
Division C would otherwise both cite as bare `"C"`, an ambiguity worth avoiding. Every
Appendix-derived citation is prefixed `Appendix-` instead, kept entirely separate from the
`division` variable used to prefix ordinary citations (so the next real Division heading after
an appendix still picks up cleanly from whatever it was before).

Because `Appendix`/`AppendixPart` are rank ≤ 2, recognizing them as headings also resets
`in_notes` to `False` the moment they're reached — which is what actually stops the
false-Note bug above; no change to `RE_NOTE_ENTRY` itself was needed or made.

`AppendixArticle` is included in `ARTICLE_TYPES` (§3) alongside `Article`, so it gets the
exact same treatment everywhere that matters: its own `_body` accumulator is created, its
content is segmented into Sentence/Clause/Subclause children with chained citations (§8) —
confirmed e.g. `Appendix-D-1.1.1.` → Sentence `Appendix-D-1.1.1.(1)` — and its Markdown
"Sentences" column and the Summary's Sentence/Clause/Subclause totals include it.

Appendix C, unlike D, has no further sub-heading structure at all below its own title (just
body text, tables, and figures directly) — confirmed by inspection; nothing further needed,
its Table/Figure captions correctly resolve `owner_citation` to bare `Appendix-C`.

## 7. Main document walk and tree assembly

Single pass over every page, top to bottom, over each page's lines flattened across all its
PDF blocks into one reading-order stream (§3). A stack of `(rank, node)` represents the
current path from the Volume root to the innermost open node. For each recognized
heading/Note line:

1. Pop the stack while its top has `rank >= this node's rank` (closes any sibling or deeper
   node that was still open).
2. The new top of stack is the parent; append the new node to `parent["children"]` and push
   `(rank, new_node)`.
3. Also append the new node to a flat `flat_nodes` list, in document order — this list is
   what page/length finalization and the Markdown summary iterate over.

Each node's `page0` (0-indexed) is the page it was first seen on. A node's `citation` is
built contextually: Division uses just its letter; everything under a Division prefixes with
`{division}-{identifier}` (e.g. `B-9.10.14.1.`); NotesContainer uses `Notes-{division}-{id}`;
Note uses `Note:{identifier}`; Appendix and everything under it uses `Appendix-{identifier}`
(§6).

Body text lines that are neither a heading nor a Note (while `in_notes` is false, or when
`in_notes` is true but the line doesn't match `RE_NOTE_ENTRY`) are appended to the
**currently open Article's (or AppendixArticle's)** `_body` accumulator
(`current_article["_body"]`), if one is open — this is the raw material for
Sentence/Clause/Subclause segmentation (§8). Any text that appears before the first
Article/AppendixArticle of a Part/Section (or when none is open, e.g. Division/Part/Section
preamble text) is simply dropped — it's out of scope for this index. `current_article` is
reset to `None` whenever any other heading is parsed, so body accumulation stops the moment
the next heading of any kind begins.

## 8. Sentence / Clause / Subclause segmentation

Runs once per Article/AppendixArticle (§3's `ARTICLE_TYPES`), after the full document walk,
over that node's accumulated `_body` lines: `(page0, y0, x0, text)` tuples.

**Marker recognition:** a line matching `^([A-Za-z0-9]{1,4})\)\s+(.*)$` carries a marker
token (the part before `)`). `classify_marker(token)` labels it:

- all digits → `sentence`
- single character, not a roman letter (`i v x l c d m`) → `clause`
- single character, a roman letter → `ambiguous`
- multi-character, a valid Roman numeral (checked against a precomputed set of Roman
  numerals for 1–60) → `subclause`
- multi-character, not a valid Roman numeral → `noise` (ignored)

**Splitting into Sentences:** body lines are split at every line classified `sentence`;
everything before the first Sentence marker (preamble) is dropped. Each segment's own lines
are then walked to build nested Clause/Subclause children:

- A **digit** line was already the Sentence boundary — skipped when re-scanning the segment.
- **Ambiguous** (single roman-letter) markers are resolved, in priority order:
  1. If the token is exactly the *next expected clause letter* (tracked per Sentence,
     starting at `"a"` and incrementing after each single-letter Clause) → `clause`.
     This handles the common case of `a) b) c) ...` where a letter like `i` or `v` would
     otherwise look Roman.
  2. Else, if this Sentence has at least one line already classified as an unambiguous
     `clause` *and* one as an unambiguous `subclause`, compute
     `threshold = (median(clause x-positions) + median(subclause x-positions)) / 2` up
     front for the whole segment, and classify by which side of that threshold the
     ambiguous line's own `x0` falls on.
  3. Else, if a Clause is already open on the *same page* and this line's `x0` is more than
     8pt to the right of that clause's `x0` → `subclause` (indentation fallback).
  4. Else → `clause` (default).
- A `clause`-classified line opens a new Clause under the current Sentence and becomes the
  reference point for rule 3 above; a `subclause`-classified line is attached under the
  *currently open* Clause (dropped if none is open).

Each Sentence/Clause/Subclause node: `{type, identifier: "(token-lowercased)", citation,
page0, children}`. `identifier` is always parenthesized and lowercase regardless of the
source token's case or the Roman-numeral casing on the page. `citation` chains from the
owning Article's (or AppendixArticle's) own citation: Sentence = `{article_citation}
{identifier}`, Clause = `{sentence_citation}{identifier}`, Subclause =
`{clause_citation}{identifier}` — e.g. Article `B-1.1.1.1.` → Sentence `B-1.1.1.1.(1)` →
Clause `B-1.1.1.1.(1)(a)` → Subclause `B-1.1.1.1.(1)(a)(i)`, or AppendixArticle
`Appendix-D-1.1.1.` → Sentence `Appendix-D-1.1.1.(1)`, matching the numbering convention in
§1 (with the division/appendix prefix kept, consistent with every other node's `citation`,
even though the PDF's own printed captions omit it).

## 9. Page-range finalization

Two passes assign `end_page`/`length` (1-indexed) to every node:

- **Skeleton nodes** (everything in `flat_nodes`): `end_page0 = next flat_node's page0`, or
  the document's last page for the very last node in the list. This is a document-order
  "next node starts, so I end" rule, applied uniformly regardless of type or depth — this is
  exactly the rule that produced §6's inflated `Notes to Part 10` length before the Appendix
  fix: with nothing recognized in between, its "next node" was ~76 pages later.
- **Nested nodes** (Sentence/Clause/Subclause, only present under `ARTICLE_TYPES`): the same
  next-sibling rule, applied recursively via `finalize_nested_ends` — a child's end is its
  next sibling's start page, or its parent's own end page if it's the last child.

Final fields on every node: `page` (1-indexed start), `end_page` (1-indexed, inclusive),
`length = end_page - page + 1` (in pages; a node's own start page is not deducted from a
later node's range — a single page can count toward the length of more than one node, since
several structural levels can start/end on the same physical page).

Table/Figure entries only get a 1-indexed `page` (no range/length — a caption is a point, not
a span; see §4 on `continuation` for the multi-page-table caveat).

## 10. Outputs

### `output/bcbc_mo_index.json`
```json
{"volume": <full nested tree, every level Volume..Subclause, Appendix..AppendixArticle>,
 "tables": [<flat list>],
 "figures": [<flat list>]}
```
Full fidelity — this is the only place Sentence/Clause/Subclause detail (page/length and
`citation`) is written.

### `output/bcbc_mo_index.md`
Human-readable:
1. **Summary** — a count per level (Division, Part, NotesContainer, Note, Section,
   Subsection, Article, Appendix, AppendixPart, AppendixSection, AppendixArticle, TableGroup,
   Sentence, Clause, Subclause, Table, Figure). Sentence/Clause/Subclause counts are totals
   across the whole document (both `ARTICLE_TYPES`), not per-Article.
2. **Document Level Index** — one row per node from Volume down to Article/Note/
   AppendixArticle (inclusive); Sentence/Clause/Subclause are *not* listed as their own rows
   (would run to tens of thousands) but each Article/AppendixArticle row's own **Sentences**
   column shows its direct child count. Rows are indented (`&nbsp;&nbsp;` × depth) to show
   nesting; columns: Level, Citation, Title, Page, End Page, Length, Sentences.
3. **Table Index** / **Figure Index** — each flat list, sorted by page, as `#, Identifier,
   Title, Owner, Forming Part Of, Page, Cont'd` — `Owner` is `owner_citation`, `Forming Part
   Of` is the verbatim `forming_part_of` text when present, `Cont'd` is `yes` when
   `continuation` is true.

## 11. Known limitations / deliberate scope cuts

- Preamble text before a Part/Section/Division's first Article (or before any Article/
  AppendixArticle at all) is dropped, not attached to any node — it was out of scope for a
  boundary/page/length structural index.
- A Note's own body text is only ever its first line — continuation lines of a multi-line
  Note (plain `BookAntiqua`, same as any other body text) aren't distinguished from an
  adjacent Note's or Article's body and are dropped, same as other undifferentiated body
  text. Unlike heading titles (§3) and captions (§4), Notes have no font-based signal to
  anchor a continuation-lookahead on — fixing this needs its own accumulate-until-next-
  Note/heading pass, not yet implemented. Note that this only truncates a Note's own `title`
  text — its `page`/`end_page`/`length` are still computed correctly (§9's "next node in
  document order" rule finds the true next heading/Note regardless of how much undifferentiated
  body text sits in between). Confirmed directly on two of Division C's own Notes,
  `Note:A-2.2.7.3` (13 pages) and `Note:A-2.3.1` (22 pages): spot-checked their full page
  ranges for any missed Arial-Black heading or embedded Table/Figure caption (found none) and
  read a text sample directly — both are genuinely long, single continuous notes with their
  own internal non-bold outline numbering (e.g. `2.1.1. Automatic Sprinkler Systems` followed
  by bullet points), not a sign of any further undetected heading type the way Appendix C/D
  (§6) was.
- One confirmed residual false-positive Note: a body-text line wrap that happens to start
  with a token shaped like a Note reference (`C-B`, from `...known as Schedules A, B, C-A
  and` / `C-B and located at the end of Division C...`) gets misread as a new Note. Tightening
  `RE_NOTE_ENTRY` to require e.g. a digit right after the hyphen was considered and rejected —
  checked directly against all 804 recognized Notes first, and found it would break ~26
  legitimate glossary/definition-style Notes that are genuinely letter-shaped (`A-Table`,
  `A-weighted:`, `I-joists`, `U-value`, `R-value`). No font or layout signal distinguishes a
  real Note's first line from an ordinary body-text line wrap that happens to fit the same
  shape; left as a known, narrow (1 confirmed instance in 804) source of noise rather than
  risk breaking real entries to chase it.
- One confirmed citation collision that is a **source-document issue, not a parsing bug**:
  the PDF itself prints two different Articles under the same number — `10.1.1.1. Scope`
  (correctly under Subsection `10.1.1.`) and, further down the same page, `10.1.1.1. Defined
  Terms` (nested under Subsection `10.1.2.`, so almost certainly meant to read `10.1.2.1.` —
  likely a typo in the source). Both are indexed faithfully as printed (`citation:
  "B-10.1.1.1."` resolves to two different Article nodes) rather than silently "corrected" to
  a guessed number, which would risk introducing this indexer's own error into what's meant
  to be an accurate reference.
- `RE_NOTE_ENTRY` captures only the first whitespace-delimited token as a Note's `identifier`
  — exactly right for the common `A-9.8.4.  Text...` case, too coarse for a less common
  Note-naming convention also used in this document: `A-Table 4.1.2.1.Importance Categories
  for Buildings.` becomes identifier `A-Table`, with the distinguishing table number left
  sitting at the start of `title` instead. Confirmed 21 different Notes collapse to the same
  `Note:A-Table` citation this way (plus 2 more to `Note:R-value`) — no content is lost, but
  they aren't distinguishable by citation alone. Not fixed: widening the identifier capture to
  include a second token when the first is followed by a bare number only works when the
  source has a space before that number, and — like the two Articles above — some of these
  lines don't; chasing that reintroduces the same separator-optionality risk already reasoned
  through for `RE_ARTICLE` (§3), for a citation-granularity improvement rather than a
  correctness fix.
- Table/Figure entries are not inserted into the hierarchy tree — they stay a flat,
  page-ordered list, now carrying `owner_citation`/`forming_part_of` (§4) rather than being
  nested as children of the Article/Note/AppendixArticle they belong to.
- `continuation` (§4) flags a table/figure caption whose title ends in `(continued)`; it does
  **not** merge that entry's page back into an earlier page range for the same table — each
  page a caption appears on is its own flat entry.
- 10 of 492 Table/Figure entries (as of the full-document run this spec was last checked
  against) have an empty `title`. Spot-checked one directly (`Table A-9.11.1.4.-C`): its
  caption is the very last line on its page, with the title wrapping onto the next page —
  detection runs per page (§7/§4), so nothing on the next page is ever looked at. The rest
  weren't individually re-checked but are presumed to be the same page-boundary case, or a
  caption whose title line genuinely isn't in one of the fonts §4 checks for. Fixing the
  page-boundary case would mean carrying a lookahead across the page loop in `build_index`,
  not just across blocks within a page — a bigger structural change than made here.
- A very small number of titles end mid-phrase because that's genuinely how the source PDF
  lays them out — confirmed on `Table 4.1.6.2.-B`, whose only title line literally is `Basic
  Roof Snow Load Factor for`, immediately followed by its `Forming Part of Sentence
  4.1.6.2.(2)` line with nothing missed in between. Not a parsing bug to fix, just a faithful
  transcription of an oddly-authored caption.
- The whole document is one synthetic Volume; there is no way to represent a document that
  *does* have multiple real Volumes without changing this assumption. Only Appendices C and D
  were confirmed and handled (§6) — if the document has other non-Division top-level sections
  using yet another numbering convention, they'd hit the same originally-unrecognized-heading
  failure mode Appendix C/D did, undetected until spot-checked the same way.
- Segmentation logic (§8) was validated against this specific document family (BC/National
  Building Code marker conventions); a document using different marker conventions (e.g.
  bracketed numerals, different indent conventions) would need re-validation.
