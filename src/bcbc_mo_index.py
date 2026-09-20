#!/usr/bin/env python3
"""
Structural indexer for "MO Package BCBC MRK signed.pdf".

Builds a hierarchical index of the document, following the numbering
convention used throughout the source: the 1st number is the Part, the
2nd the Section, the 3rd the Subsection, the 4th the Article; detailed
provisions below Article level are Sentences (in brackets), broken down
into Clauses and Subclauses:

    Volume -> Division -> Part -> Section -> Subsection -> Article ->
              Sentence -> Clause -> Subclause
                        \\-> Notes to Part -> Note   (sibling of Section, under Part's Division)

Two Appendices (C and D, confirmed inserted after Division B's own Part 10
and before Division C) use a separate but parallel numbering scheme - see
"Appendix headings" below - producing an analogous chain: Appendix ->
AppendixPart ("Section D-1") -> AppendixSection ("D-1.1.") ->
AppendixArticle ("D-1.1.1.") -> Sentence -> Clause -> Subclause, sibling of
Division under Volume.

plus a flat index of Table and Figure captions, each anchored to the
Article/Note it belongs under, with a page number and (for hierarchy
nodes) a page length.

How headings are found
-----------------------
This specific PDF's own bookmark outline is too coarse to drive extraction
directly (`doc.get_toc()` only reflects the source files that were merged to
produce it, e.g. "04 2023-10-26_NBC2020p1 Division B Part 1.FIN") - unlike a
fully-bookmarked BCBC PDF, which has a real Volume/Division/.../Article
outline. So headings are recognized directly in the page text instead.

Recognizing a REAL heading (not a citation reference wrapped mid-sentence,
e.g. "...as required in Subsection 3.1.3.1. of Division A") requires more
than a text pattern. Inspecting the PDF's own span metadata confirmed a
reliable, font-based signal instead:

  - Division / Part / Notes-to-Part / Section / Subsection / Article
    headings are rendered in "Arial-Black".
  - Body text and individual Note entries use "BookAntiqua".
  - A genuine Table/Figure CAPTION uses "Arial-BoldMT" (bold, but distinct
    from Arial-Black) - a body-text mention of the same table/figure number
    (e.g. "Figure A-9.8.4.-B in Note A-9.8.4. of Division B.)") renders in
    plain BookAntiqua and is correctly rejected.

A pattern match is only accepted when the line's font carries the expected
weight, which eliminates false positives from wrapped citation text.

A heading's number+word ("Part 1", "Section 1.1.") and its title text are
not always the same physical text line, and not even always the same
PDF layout block - e.g. "Part 1" and its title "Compliance" render as two
separate Arial-Black blocks, and a long Section/Subsection/Article title
can wrap onto a further Arial-Black line in yet another block (confirmed:
"Section 1.3. Divisions A, B and C of this" continues as "Code" in a
separate block on the same page). Heading and caption detection therefore
runs over each page's lines flattened into one top-to-bottom stream
(sorted by position across all of the page's PDF layout blocks, not
per-block), so a title can be picked up regardless of which block PyMuPDF
placed its continuation line in: after any recognized heading, subsequent
lines are folded into its title as long as they keep the same Arial-Black
weight and do not themselves match a heading pattern (i.e. they're plain
continuation text, not the next heading) - with one override: a
heading-shaped continuation line is still folded in if the title text
captured immediately before it trails off on "and"/"or" (confirmed real
case, one instance in the whole document: Subsection 2.2.9.'s own title
cites another heading by name mid-wrap, "...for Subsection 10.2.3. and" /
"Section 10.3." - without the override, "Section 10.3." alone on its own
line reads as a genuine new Section, prematurely closing the real
Subsection and reparenting its own Articles one level too shallow under a
bogus node).

No literal "Volume" (or "Book") heading exists anywhere in this PDF's text
(confirmed by a full-document scan) - the whole package is treated as one
synthetic "Volume" root spanning every page, matching the schema the user
asked for.

Appendix headings (Appendix C, Appendix D - both confirmed real, inserted
after Division B's own "Notes to Part 10" and before Division C starts)
use a distinct, letter-prefixed numbering scheme that the patterns above
don't recognize at all: "Appendix D" doesn't match the Division pattern
(letter-only, no "Division" keyword), and "D-1.1.1. Scope" doesn't match
the Subsection pattern (requires pure digits before the first dot). Left
unrecognized, these headings used to fall through to the Note check while
`in_notes` was still (wrongly) true from whichever "Notes to Part N" last
set it - and since nothing was resetting that flag, it then stayed stuck
true for the rest of both appendices. Confirmed by direct inspection: this
mis-tagged 133 genuine Appendix C/D headings as spurious "Note" nodes (with
their own body content silently dropped instead of being segmented into
Sentences), inflated "Notes to Part 10"'s own page length to wrongly
span all of Appendix C and D (~76 pages it doesn't actually contain), and
mis-anchored every Appendix C/D Table/Figure's `owner_citation` to
whatever real Note happened to be open beforehand. Fixed by adding
dedicated patterns for "Appendix X", "Section D-N ..." (Part-equivalent,
no trailing dot after the number - confirmed distinct from a regular
Section's own "N.N." plus dot), "D-N.N. ..." (Section-equivalent), and
"D-N.N.N. ..." (Article-equivalent, where body content actually lives -
confirmed it uses the same "1)"/"a)"/"i)" marker convention as the main
document, so Sentence/Clause/Subclause segmentation applies to it
identically). These are recognized as their own types (Appendix,
AppendixPart, AppendixSection, AppendixArticle) rather than reusing
Division/Part/Section/Article, specifically so an Appendix C and a real
Division C - which would otherwise both cite as bare "C" - stay
unambiguous: every Appendix-derived citation is prefixed "Appendix-"
(e.g. "Appendix-D-1.1.1.", vs. a real Article's "B-9.10.14.1.").

Two further gaps, found by an exhaustive scan of every Arial-Black line in
the document that neither matched a heading pattern nor got folded into a
preceding one's title continuation (confirmed this scan returns zero
unaccounted-for lines once both are fixed):

  - Two Articles have no space at all between the number and the title in
    the extracted text ("3.2.2.64.Group D, up to 2 Storeys",
    "3.8.5.7.Adaptable Dwelling Unit Bathrooms" - their own sibling
    headings on the same page do have the normal space, so this looks like
    a PDF-extraction quirk specific to these two lines). The Article
    pattern's separator was relaxed from "one or more spaces" to "zero or
    more" to catch these - deliberately not applied to the Subsection
    pattern too, since Article is checked first and a 4-part number must
    never be left for the (still strict) Subsection pattern to partially
    swallow.
  - Part 9 - by far the largest Part - ends its own narrative content with
    two bare, unnumbered divider headings grouping its compiled tables,
    "Fire and Sound Resistance Tables" and "Span Tables" (confirmed the
    only two of their kind in the whole document). Recognized as their own
    "TableGroup" type; without it, everything from the first such divider
    to "Notes to Part 9" - Table and Figure captions included - was
    silently absorbed as undifferentiated body text of whatever Article
    happened to be open beforehand (confirmed: that Article's own page
    length was inflated to 318 pages before this fix).

Sentence/Clause/Subclause numbering ("1)", "a)", "i)") only exists as
indented body text below Article level - never bookmarked, never a distinct
font. These are segmented from each Article's own accumulated body lines
using the marker classification approach validated on this same family of
BC/National Building Code documents: a digit marks a Sentence; a single
non-roman-shaped letter is an unambiguous Clause; a multi-character roman
numeral is an unambiguous Subclause; a single roman-shaped letter (i, v, x,
l, c, d, m) is ambiguous and resolved by (in priority order) whether it is
the next expected clause letter, this Sentence's own clause/subclause
indent threshold, and finally same-page indent vs. the previous clause.
Each Sentence/Clause/Subclause node carries a full dotted citation built
from its Article's own citation plus its own bracketed identifier(s), e.g.
Article "B-1.1.1.1." -> Sentence "B-1.1.1.1.(1)" -> Clause
"B-1.1.1.1.(1)(a)" -> Subclause "B-1.1.1.1.(1)(a)(i)".

A caption is only ever recognized in Arial-BoldMT/BookAntiqua-Bold/
PalatinoLinotype-Bold - not "ArialNarrow-Bold", the condensed font family
reserved for a table's own header/data cells (§ below). This gate applies
to the caption *trigger* itself, not just to title-continuation lines:
confirmed one real table's own cross-reference cell, rendered
ArialNarrow-Bold, reading exactly "Table 9.10.3.1.-A" (the same identifier
as a genuine caption elsewhere in the document) - without this exclusion
it was misread as a second, spurious caption for that same table, with an
empty title since nothing useful followed it.

Table/Figure captions are anchored to whichever Article or Note is
currently open when the caption is encountered (`owner_citation`). Many
captions are also immediately followed by an explicit cross-reference line
("Forming part of Sentence 1.1.1.1.(5)", "Forming Part of Sentences
3.1.2.1.(1) and 3.1.2.2.(1)") - captured verbatim as `forming_part_of`
(this line's own font weight varies across the document - confirmed both
bold and non-bold - so it's matched on text, not font, and title
accumulation always stops there regardless). A title ending in
"(continued)" (confirmed on a handful of tables spanning more than one
page, e.g. "Insulation Materials(6) (continued)") is flagged
`continuation: true`; each continuation is recorded as its own entry
rather than merged with the table's first page - reconstructing one true
multi-page span per table would need actual table-grid analysis, out of
scope here.

A caption's title can otherwise run directly into the table's own header
row/cells with no text marker in between - title accumulation also stops
at a "Notes to Table/Figure X:" footnote intro line (confirmed recurring,
e.g. "Notes to Figure A-3.4.6.4.:"), at any line sharing a y0 position with
another line on the page (the signature of a multi-column header row, e.g.
several column headings at the same height - a genuine title line never
does), and - the strongest signal, confirmed by directly inspecting the
Division B Part 9 thermal-resistance/insulation tables where this used to
leak (e.g. "Table A-9.36.2.8.(1)-C") - at any line whose font is a
"Narrow" variant: every caption/title in this document renders in
Arial-BoldMT (or, in a couple of appendices, BookAntiqua-Bold /
PalatinoLinotype-Bold - never a Narrow face), while every table's own
header/data cells consistently use ArialNarrow/ArialNarrow-Bold, a
distinct condensed font family used only for compact tabular data. A
3-line cap is also kept as a backstop (every confirmed genuine title is
1-3 lines).

Two known gaps, deliberately left as-is rather than "fixed":

  - The source PDF itself genuinely prints two different Articles under
    the same number - "10.1.1.1. Scope" (under Subsection 10.1.1.) and,
    further down the same page, "10.1.1.1. Defined Terms" (nested under
    Subsection 10.1.2., so almost certainly meant to read "10.1.2.1." -
    likely a typo in the source document itself). Both are indexed
    faithfully as printed rather than silently "corrected" to a guessed
    number, which would risk introducing an error of this indexer's own
    into what's meant to be an accurate reference; the result is one
    confirmed citation collision (`B-10.1.1.1.` resolves to two different
    Articles) that a consumer of the JSON should be aware of.
  - `RE_NOTE_ENTRY` captures only the first whitespace-delimited token as
    a Note's identifier, which is exactly right for the common
    "A-9.8.4.  Text..." case but too coarse for a different, less common
    Note-naming convention also used in this document - "A-Table
    4.1.2.1.Importance Categories for Buildings." becomes identifier
    "A-Table" with the distinguishing table number left sitting at the
    start of the `title` field instead. Confirmed 21 different Notes all
    collapse to the same `Note:A-Table` citation this way (plus 2 more to
    `Note:R-value`) - no content is lost, but they're not distinguishable
    by citation alone. Not fixed: widening the identifier capture to
    include a second token when the first is followed by a bare number
    only works when the source has a space before that number, and (like
    the two Articles above) some of these lines don't - chasing that
    reintroduces exactly the kind of separator-optionality question this
    file is already careful about elsewhere, for a citation-granularity
    improvement rather than a correctness fix.

Output (written to output/, alongside the project's other generated results)
------
  output/bcbc_mo_index.json - full-fidelity tree (every level down to
                        Subclause, each with its own citation; Notes,
                        Tables, Figures), machine-readable.
  output/bcbc_mo_index.md   - human-readable index: full hierarchy down to
                        Article/Note (with page + length for every node),
                        plus separate Table and Figure indexes (each row
                        showing its owning citation and, where present, its
                        "Forming part of" cross-reference). Sentence/
                        Clause/Subclause are summarized as counts per
                        Article rather than listed individually (a full
                        per-sentence listing would run into the tens of
                        thousands of rows) - full detail for those,
                        including citations, is in the JSON.

Usage:
    python3 src/bcbc_mo_index.py                  # uses data/<default PDF>
    python3 src/bcbc_mo_index.py /path/to/other.pdf   # index a different PDF
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import pymupdf as fitz

# Anchored to this script's own location (src/), not the current working
# directory, so paths stay correct however/wherever the script is invoked.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
JSON_OUT = str(PROJECT_ROOT / "output" / "bcbc_mo_index.json")
MD_OUT = str(PROJECT_ROOT / "output" / "bcbc_mo_index.md")

# ---------------------------------------------------------------------------
# Heading / caption patterns
# ---------------------------------------------------------------------------

RE_DIVISION = re.compile(r"^Division\s+([A-Z])\s*$")
RE_NOTES_CONTAINER = re.compile(r"^Notes to Part\s+(\d+)\s*$")
RE_PART = re.compile(r"^Part\s+(\d+)\s*$")
RE_SECTION = re.compile(r"^Section\s+(\d+\.\d+)\.\s*(.*)$")
# `\s*`, not `\s+`: confirmed two Articles in the source PDF text extraction
# have no space at all between the number and title ("3.2.2.64.Group D, up
# to 2 Storeys", "3.8.5.7.Adaptable Dwelling Unit Bathrooms" - their own
# sibling headings on the same page do have the normal space, so this looks
# like a PDF-extraction quirk specific to these two lines, not a real
# formatting difference). Safe to relax only here, not on RE_SUBSECTION
# below: Article is checked before Subsection in HEADING_PATTERNS, so a
# 4-part number is always claimed by this pattern first - if RE_SUBSECTION
# were *also* relaxed to `\s*`, its own 3-part prefix could wrongly match
# the first three segments of a 4-part number with no intervening
# whitespace to block it (exactly the false-positive the ordering comment
# below already warns about), so it stays strict.
RE_ARTICLE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)\.\s*(.*)$")
RE_SUBSECTION = re.compile(r"^(\d+\.\d+\.\d+)\.\s+(.*)$")
# Unnumbered divider headings grouping a block of Part 9's own compiled
# Tables (confirmed: exactly two in the whole document, "Fire and Sound
# Resistance Tables" and "Span Tables", both Arial-Black, both bare -
# no number, no other recognized pattern). Deliberately narrow (must
# literally end in the word "Tables") rather than a general "any orphaned
# Arial-Black line is a heading" catch-all: found by an exhaustive scan of
# every Arial-Black line in the document that neither matched a heading
# pattern nor got folded into a continuation, so this pattern's scope is
# know to be complete against this specific document, not a guess.
RE_TABLE_GROUP = re.compile(r"^[A-Z][A-Za-z ]*\bTables\s*$")
RE_NOTE_ENTRY = re.compile(r"^([A-Z]-\S+(?:\s+(?:and|to)\s+\(\d+\))*)\s+(.*)$")
RE_CAPTION = re.compile(r"^(Table|Figure)\s+(\S.*)$")
RE_FORMING_PART = re.compile(r"^forming part of\s+(.+)$", re.IGNORECASE)
RE_NOTES_TO_CAPTION = re.compile(r"^notes? to (table|figure)\s*", re.IGNORECASE)
RE_CONTINUED = re.compile(r"\(continued\)\s*$", re.IGNORECASE)

# Appendices (confirmed: Appendix C and D, inserted after Division B's own
# Part 10 and before Division C) use a parallel but distinct numbering
# scheme, letter-prefixed rather than pure digits, and were previously not
# recognized as headings at all - "Appendix D" doesn't match RE_DIVISION
# (no bare-letter-only pattern), and "D-1.1.1. Scope" doesn't match
# RE_SUBSECTION (requires pure digits before the first dot). Left
# unrecognized, they fell through to the Note check while `in_notes` was
# still (wrongly) true from whatever "Notes to Part N" last set it, and
# since `in_notes` is never reset except by a rank<=2 heading (see
# build_index), it then stayed stuck true for the rest of both appendices -
# confirmed this mis-tagged 133 genuine Appendix C/D headings as "Note"
# nodes, plus a handful of coincidental body-text matches ("C-3,", "C-B").
RE_APPENDIX = re.compile(r"^Appendix\s+([A-Z])\s*$")
RE_APPENDIX_PART = re.compile(r"^Section\s+([A-Z])-(\d+)\s+(.*)$")
RE_APPENDIX_ARTICLE = re.compile(r"^([A-Z])-(\d+\.\d+\.\d+)\.\s+(.*)$")
RE_APPENDIX_SECTION = re.compile(r"^([A-Z])-(\d+\.\d+)\.\s+(.*)$")

RANK = {"Division": 1, "Part": 2, "NotesContainer": 2, "Section": 3,
        "Subsection": 4, "Article": 5, "Note": 6,
        "Appendix": 1, "AppendixPart": 2, "AppendixSection": 3, "AppendixArticle": 5,
        "TableGroup": 3}

# The two node types that directly hold Sentence/Clause/Subclause children -
# "Article" under the regular Part.Section.Subsection.Article numbering,
# "AppendixArticle" under an Appendix's own parallel numbering (§ above).
ARTICLE_TYPES = ("Article", "AppendixArticle")

# Article (4-part number) is checked before Subsection (3-part number); a
# 3-part regex can never falsely match a 4-part number here anyway (after
# the mandatory dot there must be whitespace per the regex, but a 4-part
# number has another digit there instead), but the explicit order keeps the
# intent obvious. Subsection/Article are matched purely by their position
# in this same Part.Section.Subsection.Article numbering scheme (3 vs. 4
# dotted numbers) - no keyword like "Section"/"Part" precedes them in the
# source text. Same reasoning for AppendixArticle (3-part, e.g. "D-1.1.1.")
# before AppendixSection (2-part, "D-1.1."): a 2-part regex can't actually
# match a 3-part heading either (same trailing-dot-then-whitespace
# argument), so order is for readability, not correctness.
HEADING_PATTERNS = [
    ("Division", RE_DIVISION),
    ("NotesContainer", RE_NOTES_CONTAINER),
    ("Part", RE_PART),
    ("Section", RE_SECTION),
    ("Article", RE_ARTICLE),
    ("Subsection", RE_SUBSECTION),
    ("Appendix", RE_APPENDIX),
    ("AppendixPart", RE_APPENDIX_PART),
    ("AppendixArticle", RE_APPENDIX_ARTICLE),
    ("AppendixSection", RE_APPENDIX_SECTION),
    ("TableGroup", RE_TABLE_GROUP),
]


def classify_heading_line(text, font):
    if "Black" not in font:
        return None
    for ntype, pattern in HEADING_PATTERNS:
        m = pattern.match(text)
        if m:
            return ntype, m
    return None


RE_ENDS_WITH_CONJUNCTION = re.compile(r"\b(?:and|or)\s*$", re.IGNORECASE)


def _is_heading_continuation(text, font, preceding_text):
    """True for a line that continues a heading's title onto a further
    line/block: same Arial-Black weight, and either not itself a new
    heading, or - when `preceding_text` (whatever title text was captured
    immediately before this line) dangles on a trailing "and"/"or" - a
    heading-shaped line that's actually still the same sentence. Confirmed
    real case: a Subsection's own title cites another Section by name,
    wrapping right at the citation - "...for Subsection 10.2.3. and" /
    "Section 10.3." is one continuous cross-reference, not two headings.
    Without this override, "Section 10.3." alone on its own line reads as
    a genuine new Section, prematurely closes the real Subsection, and
    reparents its own Articles one level too shallow under a bogus node.
    """
    if "Black" not in font:
        return False
    if classify_heading_line(text, font) is None:
        return True
    return bool(RE_ENDS_WITH_CONJUNCTION.search(preceding_text.strip()))


def _consume_while(lines, idx, predicate, max_lines=None):
    """Collect (text of) lines[idx:] while predicate(text, font, y0, parts)
    holds - `parts` is whatever's been collected so far, so a predicate can
    make a line's inclusion depend on the text immediately before it -
    stopping early after max_lines lines if given. Returns (collected_texts,
    index of first line not consumed).
    """
    parts = []
    while idx < len(lines) and (max_lines is None or len(parts) < max_lines):
        y0, _, text, font = lines[idx]
        if not predicate(text, font, y0, parts):
            break
        parts.append(text)
        idx += 1
    return parts, idx


def _multi_column_rows(page_lines):
    """y0 values (rounded to 1pt) shared by 2+ lines on the page - the
    signature of a multi-column table row (e.g. several bold header cells
    sitting at the same height), and never a caption/heading's own prose
    title line: confirmed directly against this PDF that every title line,
    however long, sits alone at its own y0, while a table's header row
    consistently has 2+ cells at one shared y0 (e.g. "Document Number(2)" /
    "Title of Document" / "Code Reference" in Table D-1.1.2.'s header, all
    at y0=102.3). Used to stop title-continuation before it walks into a
    table's own header row instead of the caption's title.
    """
    counts = Counter(round(y0, 1) for y0, _x0, _t, _f in page_lines)
    return {y for y, n in counts.items() if n > 1}


# ---------------------------------------------------------------------------
# Sentence / Clause / Subclause marker classification
# ---------------------------------------------------------------------------

ROMAN_CHARS = set("ivxlcdm")


def _valid_romans(limit=60):
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = set()
    for n in range(1, limit + 1):
        rem, s = n, ""
        for v, sym in vals:
            while rem >= v:
                s += sym
                rem -= v
        out.add(s)
    return out


VALID_ROMANS = _valid_romans()
RE_MARKER = re.compile(r"^([A-Za-z0-9]{1,4})\)\s+(.*)$")


def classify_marker(token):
    """'sentence' | 'clause' | 'subclause' | 'ambiguous' | 'noise'."""
    if token.isdigit():
        return "sentence"
    t = token.lower()
    if len(t) == 1:
        return "ambiguous" if t in ROMAN_CHARS else "clause"
    return "subclause" if t in VALID_ROMANS else "noise"


def segment_article_body(body_lines, article_citation):
    """body_lines: [(page0, y0, x0, text), ...] accumulated for one Article.
    article_citation: the owning Article's own citation (e.g. "B-1.1.1.1."),
    used as the prefix for every Sentence/Clause/Subclause citation below it.
    Returns a list of Sentence nodes, each with nested Clause -> Subclause
    "children". Lines before the first Sentence marker (preamble) are
    dropped - out of scope for a boundary/page/length index.
    """
    segments, cur_seg = [], None
    for pno, y0, x0, text in body_lines:
        m = RE_MARKER.match(text)
        if m and classify_marker(m.group(1)) == "sentence":
            cur_seg = {"token": m.group(1), "lines": [(pno, y0, x0, text)]}
            segments.append(cur_seg)
        elif cur_seg is not None:
            cur_seg["lines"].append((pno, y0, x0, text))

    sentence_nodes = []
    for seg in segments:
        seg_markers = []
        for pno, y0, x0, text in seg["lines"][1:]:
            mm = RE_MARKER.match(text)
            if mm:
                seg_markers.append((x0, mm.group(1)))
        clause_x = [x for x, tok in seg_markers if classify_marker(tok) == "clause"]
        subclause_x = [x for x, tok in seg_markers if classify_marker(tok) == "subclause"]
        threshold = ((statistics.median(clause_x) + statistics.median(subclause_x)) / 2
                     if clause_x and subclause_x else None)

        first_pno = seg["lines"][0][0]
        sentence = {"type": "Sentence", "identifier": f"({seg['token']})",
                    "citation": f"{article_citation}({seg['token']})",
                    "page0": first_pno, "children": []}
        cur_clause = cur_subclause = None
        parent_clause_x0 = parent_clause_page = None
        next_clause_letter = "a"

        for i, (pno, y0, x0, text) in enumerate(seg["lines"]):
            if i == 0:
                continue
            m = RE_MARKER.match(text)
            if not m:
                continue
            token = m.group(1)
            kind = classify_marker(token)
            if kind == "ambiguous":
                if token.lower() == next_clause_letter:
                    kind = "clause"
                elif threshold is not None:
                    kind = "clause" if x0 < threshold else "subclause"
                elif (parent_clause_x0 is not None and pno == parent_clause_page
                      and x0 > parent_clause_x0 + 8):
                    kind = "subclause"
                else:
                    kind = "clause"

            if kind == "clause":
                cur_clause = {"type": "Clause", "identifier": f"({token.lower()})",
                              "citation": f"{sentence['citation']}({token.lower()})",
                              "page0": pno, "children": []}
                sentence["children"].append(cur_clause)
                cur_subclause = None
                parent_clause_x0, parent_clause_page = x0, pno
                if len(token) == 1:
                    next_clause_letter = chr(ord(token.lower()) + 1)
            elif kind == "subclause" and cur_clause is not None:
                cur_subclause = {"type": "Subclause", "identifier": f"({token.lower()})",
                                  "citation": f"{cur_clause['citation']}({token.lower()})",
                                  "page0": pno, "children": []}
                cur_clause["children"].append(cur_subclause)

        sentence_nodes.append(sentence)
    return sentence_nodes


def finalize_nested_ends(node, node_end_page0):
    """Recursively assign end_page0 to Sentence/Clause/Subclause children:
    a child's end = the next sibling's start, or the parent's own end if
    it's the last child - same "next node in document order" invariant
    used for the main skeleton.
    """
    children = node.get("children", [])
    for i, child in enumerate(children):
        child_end = children[i + 1]["page0"] if i + 1 < len(children) else node_end_page0
        child["end_page0"] = child_end
        finalize_nested_ends(child, child_end)


# ---------------------------------------------------------------------------
# Main document walk
# ---------------------------------------------------------------------------

def _page_lines(page):
    """Every text line on the page, flattened across PDF layout blocks and
    sorted into one top-to-bottom (then left-to-right) reading-order stream
    - not grouped per block, since a heading's own title or a caption's own
    cross-reference line can land in a different block than the line before
    it (confirmed for both cases on this PDF). Each entry: (y0, x0, text,
    font); font is the span font name, or "/"-joined names if a line mixes
    fonts (e.g. regular + italic body text).
    """
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            fonts = {s["font"] for s in spans}
            font = fonts.pop() if len(fonts) == 1 else "/".join(sorted(fonts))
            x0, y0 = line["bbox"][0], line["bbox"][1]
            lines.append((y0, x0, text, font))
    lines.sort(key=lambda t: (t[0], t[1]))
    return lines


def build_index(pdf_path):
    doc = fitz.open(pdf_path)
    last_page0 = doc.page_count - 1

    volume_root = {"type": "Volume", "identifier": "Volume", "citation": "Volume",
                   "title": "", "page0": 0, "children": []}
    flat_nodes = [volume_root]
    stack = [(0, volume_root)]  # (rank, node); Volume = rank 0
    in_notes = False
    current_article = None
    division = None

    tables, figures = [], []

    for pno in range(doc.page_count):
        page_lines = _page_lines(doc[pno])
        row_ys = _multi_column_rows(page_lines)

        idx = 0
        while idx < len(page_lines):
            y0, x0, text, font = page_lines[idx]

            cap_m = RE_CAPTION.match(text)
            if cap_m and "Bold" in font and "Black" not in font and "Narrow" not in font:
                kind = cap_m.group(1)
                title_parts, idx = _consume_while(
                    page_lines, idx + 1,
                    lambda t, f, y, parts: "Bold" in f and "Black" not in f and "Narrow" not in f
                                    and not RE_CAPTION.match(t)
                                    and not RE_FORMING_PART.match(t)
                                    and not RE_NOTES_TO_CAPTION.match(t)
                                    and round(y, 1) not in row_ys,
                    max_lines=3,  # every confirmed genuine title is 1-2 lines;
                    # caps the damage from a table header row this page's
                    # row_ys dedup didn't catch (e.g. a wrapped header cell
                    # whose own lines don't share a y0 with any sibling cell)
                )
                forming_part = None
                if idx < len(page_lines):
                    fm = RE_FORMING_PART.match(page_lines[idx][2])
                    if fm:
                        forming_part = fm.group(1).strip()
                        idx += 1
                title = " ".join(title_parts).strip()
                entry = {
                    "type": kind, "identifier": cap_m.group(2).strip(),
                    "title": title, "page0": pno,
                    "owner_citation": stack[-1][1].get("citation", ""),
                    "forming_part_of": forming_part,
                    "continuation": bool(RE_CONTINUED.search(title)),
                }
                (tables if kind == "Table" else figures).append(entry)
                continue

            heading = classify_heading_line(text, font)
            note = None
            if heading is None and in_notes:
                nm = RE_NOTE_ENTRY.match(text)
                if nm:
                    note = nm

            if heading is None and note is None:
                if current_article is not None:
                    current_article["_body"].append((pno, y0, x0, text))
                idx += 1
                continue

            if heading is not None:
                ntype, m = heading
                rank = RANK[ntype]
                if ntype == "Division":
                    division = m.group(1)
                    identifier, title, citation = division, "", division
                elif ntype == "Part":
                    identifier, title = m.group(1), ""
                    citation = f"{division}-{identifier}"
                elif ntype == "NotesContainer":
                    identifier, title = m.group(1), ""
                    citation = f"Notes-{division}-{identifier}"
                elif ntype == "Section":
                    identifier, title = m.group(1) + ".", m.group(2).strip()
                    citation = f"{division}-{identifier}"
                elif ntype == "Article":
                    identifier, title = m.group(1) + ".", m.group(2).strip()
                    citation = f"{division}-{identifier}"
                elif ntype == "Subsection":
                    identifier, title = m.group(1) + ".", m.group(2).strip()
                    citation = f"{division}-{identifier}"
                elif ntype == "Appendix":
                    # Own citation namespace ("Appendix-<letter>...") kept
                    # deliberately distinct from a real Division's bare
                    # letter citation - Appendix C and Division C are two
                    # different things that would otherwise both cite as
                    # plain "C". Does NOT touch `division` (used to prefix
                    # ordinary Division/Part/Section/... citations) - the
                    # next real Division heading must still pick up cleanly
                    # from whatever it was before this Appendix.
                    identifier, title = m.group(1), ""
                    citation = f"Appendix-{identifier}"
                elif ntype == "AppendixPart":
                    identifier = f"{m.group(1)}-{m.group(2)}"
                    title = m.group(3).strip()
                    citation = f"Appendix-{identifier}"
                elif ntype in ("AppendixSection", "AppendixArticle"):
                    identifier = f"{m.group(1)}-{m.group(2)}."
                    title = m.group(3).strip()
                    citation = f"Appendix-{identifier}"
                else:  # TableGroup - no capture groups, the whole match is its own label
                    identifier, title = m.group(0).strip(), ""
                    citation = f"{division}-{identifier}"

                title_parts, idx = _consume_while(
                    page_lines, idx + 1,
                    lambda t, f, y, parts: _is_heading_continuation(t, f, parts[-1] if parts else title),
                )
                if title_parts:
                    title = (title + " " + " ".join(title_parts)).strip()
            else:
                ntype, rank = "Note", RANK["Note"]
                identifier = note.group(1).rstrip(".")
                title = note.group(2).strip()
                citation = f"Note:{identifier}"
                idx += 1

            while stack and stack[-1][0] >= rank:
                stack.pop()
            parent = stack[-1][1]
            new_node = {"type": ntype, "identifier": identifier, "citation": citation,
                        "title": title, "page0": pno, "children": []}
            parent["children"].append(new_node)
            stack.append((rank, new_node))
            flat_nodes.append(new_node)

            if rank <= 2:
                # Only a Division/Part/NotesContainer heading can end (or
                # start) a Notes section - a Note entry itself, or any
                # rank 3-5 heading, must never touch this flag, or every
                # container after its own first Note would silently stop
                # being recognized (confirmed: this bug produced exactly
                # one Note per NotesContainer instead of the true count).
                # Appendix/AppendixPart headings are rank<=2 too, and must
                # be: they're what ends a trailing "Notes to Part N" that
                # would otherwise stay wrongly "in notes" for the rest of
                # the document (confirmed: this is exactly what mis-tagged
                # Appendix C/D content as Notes before these were
                # recognized as headings at all - see RE_APPENDIX above).
                in_notes = (ntype == "NotesContainer")
            if ntype in ARTICLE_TYPES:
                new_node["_body"] = []
                current_article = new_node
            else:
                current_article = None

    for i, node in enumerate(flat_nodes):
        node["end_page0"] = flat_nodes[i + 1]["page0"] if i + 1 < len(flat_nodes) else last_page0

    n_articles = sum(1 for n in flat_nodes if n["type"] in ARTICLE_TYPES)
    done = 0
    for node in flat_nodes:
        if node["type"] in ARTICLE_TYPES:
            body = node.pop("_body", [])
            sentence_nodes = segment_article_body(body, node["citation"])
            node["children"].extend(sentence_nodes)
            finalize_nested_ends(node, node["end_page0"])
            done += 1
            if done % 200 == 0:
                print(f"  ...{done}/{n_articles} articles segmented", file=sys.stderr)

    for node in flat_nodes:
        node["page"] = node.pop("page0") + 1
        node["end_page"] = node.pop("end_page0") + 1
        node["length"] = node["end_page"] - node["page"] + 1

    def finalize_leaf_pages(node):
        if "end_page0" in node:
            node["page"] = node.pop("page0") + 1
            node["end_page"] = node.pop("end_page0") + 1
            node["length"] = node["end_page"] - node["page"] + 1
        for c in node.get("children", ()):
            finalize_leaf_pages(c)

    for node in flat_nodes:
        if node["type"] in ARTICLE_TYPES:
            for c in node["children"]:
                finalize_leaf_pages(c)

    for t in tables + figures:
        t["page"] = t.pop("page0") + 1

    return volume_root, flat_nodes, tables, figures


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def iter_nodes(node):
    yield node
    for c in node.get("children", ()):
        yield from iter_nodes(c)


def write_json(volume_root, tables, figures, out_path):
    payload = {"volume": volume_root, "tables": tables, "figures": figures}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=1))


def write_markdown(volume_root, flat_nodes, tables, figures, out_path):
    lines = ["# MO Package BCBC MRK signed.pdf — Structural Index", ""]

    counts = Counter(n["type"] for n in flat_nodes)
    lines.append("## Summary")
    lines.append("")
    lines.append("| Level | Count |")
    lines.append("|---|---|")
    for level in ("Division", "Part", "NotesContainer", "Note", "Section", "Subsection", "Article",
                  "Appendix", "AppendixPart", "AppendixSection", "AppendixArticle"):
        lines.append(f"| {level} | {counts.get(level, 0)} |")
    n_sentences = sum(len(n.get("children", [])) for n in flat_nodes if n["type"] in ARTICLE_TYPES)
    n_clauses = sum(len(s.get("children", [])) for n in flat_nodes if n["type"] in ARTICLE_TYPES
                    for s in n.get("children", []))
    n_subclauses = sum(len(c.get("children", [])) for n in flat_nodes if n["type"] in ARTICLE_TYPES
                       for s in n.get("children", []) for c in s.get("children", []))
    lines.append(f"| Sentence | {n_sentences} |")
    lines.append(f"| Clause | {n_clauses} |")
    lines.append(f"| Subclause | {n_subclauses} |")
    lines.append(f"| Table | {len(tables)} |")
    lines.append(f"| Figure | {len(figures)} |")
    lines.append("")
    lines.append("Sentence/Clause/Subclause are only summarized here (counts per Article) — "
                  "full per-node page/length/citation detail for every level, including those, "
                  f"is in `{JSON_OUT}`.")
    lines.append("")

    lines.append("## Document Level Index (Volume → Article, Notes to Part → Note)")
    lines.append("")
    lines.append("| Level | Citation | Title | Page | End Page | Length (pages) | Sentences |")
    lines.append("|---|---|---|---|---|---|---|")

    def walk(node, depth):
        if node["type"] not in ("Sentence", "Clause", "Subclause"):
            indent = "&nbsp;&nbsp;" * depth
            n_sent = len(node.get("children", [])) if node["type"] in ARTICLE_TYPES else ""
            title = node.get("title", "").replace("|", "\\|")
            lines.append(
                f"| {indent}{node['type']} | {node.get('citation', '')} | {title} | "
                f"{node['page']} | {node['end_page']} | {node['length']} | {n_sent} |"
            )
        for c in node.get("children", ()):
            if c["type"] not in ("Sentence", "Clause", "Subclause"):
                walk(c, depth + 1)

    walk(volume_root, 0)
    lines.append("")

    def caption_table(items, heading):
        lines.append(f"## {heading}")
        lines.append("")
        lines.append("| # | Identifier | Title | Owner | Forming Part Of | Page | Cont'd |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, entry in enumerate(sorted(items, key=lambda x: x["page"]), start=1):
            title = entry["title"].replace("|", "\\|")
            forming_part = (entry.get("forming_part_of") or "").replace("|", "\\|")
            cont = "yes" if entry.get("continuation") else ""
            lines.append(
                f"| {i} | {entry['identifier']} | {title} | {entry.get('owner_citation', '')} | "
                f"{forming_part} | {entry['page']} | {cont} |"
            )
        lines.append("")

    caption_table(tables, "Table Index")
    caption_table(figures, "Figure Index")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pdf_path", nargs="?", default=DEFAULT_PDF,
                        help=f"PDF to index (default: {DEFAULT_PDF})")
    return parser.parse_args()


def main():
    pdf_path = parse_args().pdf_path
    if not Path(pdf_path).exists():
        sys.exit(f"No such file: {pdf_path}")
    print(f"Opening {pdf_path} ...", file=sys.stderr)
    volume_root, flat_nodes, tables, figures = build_index(pdf_path)

    write_json(volume_root, tables, figures, JSON_OUT)
    write_markdown(volume_root, flat_nodes, tables, figures, MD_OUT)

    c = Counter(n["type"] for n in flat_nodes)
    print("Counts:", file=sys.stderr)
    for t, n in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {t}", file=sys.stderr)
    print(f"  {len(tables):6d}  Table", file=sys.stderr)
    print(f"  {len(figures):6d}  Figure", file=sys.stderr)
    print(f"Wrote {JSON_OUT} and {MD_OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
