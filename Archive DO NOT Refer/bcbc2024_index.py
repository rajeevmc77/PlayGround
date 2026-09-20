#!/usr/bin/env python3
"""
Structural indexer for "bcbc_2024.pdf", built from its PDF bookmarks.

Unlike "MO Package BCBC MRK signed.pdf" (see bcbc_mo_index.py), this PDF's
own bookmark outline (`doc.get_toc()`) is complete and reliable: 4227
entries, including individual Notes nested under their "Notes to Part N"
container, Figures, a real two-Volume split (Volume I / Volume II - not a
synthetic root), and Appendix C/D correctly nested as Part-level siblings
under Division B (not Division-level, as this project had to guess for the
MO Package, which has no Appendix bookmarks at all). The bookmark outline
therefore drives the whole skeleton here - Volume, Division, Part, Section,
Subsection, Article, NotesContainer, Note, Appendix, AppendixPart,
AppendixSection, AppendixArticle - by pattern-matching each bookmark
title's text (not its raw indentation level, which is noisy: it also
carries wrapper bookmarks for the merged Ministerial Order and the base
filename, and - inside some Notes - bookmarked table row/column labels
that aren't structural at all, e.g. "Level of Performance". These are
simply dropped: any bookmark title matching none of the known patterns is
ignored).

    Volume -> Division -> Part -> Section -> Subsection -> Article ->
              Sentence -> Clause -> Subclause
                        \\-> Notes to Part -> Note
    Volume -> Division -> Appendix -> AppendixPart -> AppendixSection ->
              AppendixArticle -> Sentence -> Clause -> Subclause

Two real Volumes (confirmed: "Volume I" holds Division A, Division B Parts
1-8, Appendix C/D, and Division C; "Volume II" holds only Division B's
Part 9 and Part 10 - the two large residential/energy Parts split into
their own physical book) are each written out as their own top-level tree,
under a `"volumes"` list in the JSON (plural, unlike bcbc_mo_index.py's
single synthetic `"volume"` - this document has no need for one).

Bookmarks do not reach Sentence/Clause/Subclause level, and do not cover
Table captions at all (only Figures are individually bookmarked, as a
caption-id bookmark immediately followed by a title-only bookmark - the
same two-line split bcbc_mo_index.py found in the MO Package's own PDF
text, just captured as bookmarks here instead). Both are therefore found
by a second, independent pass over the actual page text/fonts - this PDF
uses a different production entirely (HelveticaLTStd-Blk/-Bold/-Roman,
not Arial-Black/-BoldMT/BookAntiqua), confirmed by direct inspection, and
its Sentence/Clause/Subclause markers ("1)", "a)", "i)") consistently have
no space before the text that follows ("1)This Code applies...", unlike
the MO Package's "1)   This Code applies...") - confirmed on a full page
sample, not just isolated cases, so the marker pattern here always allows
zero space rather than treating it as a rare exception.

This second pass does not rediscover the skeleton - it uses the
citation/page lookup already built from the bookmarks to know which
Article/AppendixArticle a given body line or caption belongs to, and where
on a page multiple such nodes starting on the same page are ordered
(needed since bookmarks give a page number, not a Y-position) by locating
each expected heading's own line via the same pattern battery used on
bookmark titles, applied to the page's own Helvetica-Blk lines instead.

Known gap, deliberately left as-is: each Part's own large "Attributions to
Acceptable Solutions" table (one per Part - Table 4.5.1.1., 5.10.1.1.,
6.10.1.1., 8.3.1.1., 9.38.1.1., 10.4.1.1., ...) is laid out in two
side-by-side columns spanning many pages, each column its own "Table
X (continued)" caption at the same Y-height as its neighbour - confirmed
directly on Table 4.5.1.1.'s own page. This project's page-line reading
order (sorted by Y position only, then X - see `_page_lines`, unchanged
from bcbc_mo_index.py) implicitly assumes a single reading column, so
these specific two-column pages interleave the columns' text, producing
a garbled or truncated `title` for some of that family's entries (and
several extra caption rows from the second column). The rest of the
index is unaffected - the STRUCTURAL hierarchy, page ranges, and
`owner_citation` for these entries are still correct, since caption
detection itself doesn't depend on column layout, only the *title text
capture* does. Resolving this properly would need genuinely column-aware
page reading (group lines by X-range before sorting by Y within each
group), a larger change than made here.

Output (written to output/, alongside the project's other generated results)
------
  output/bcbc2024_index.json - full-fidelity tree per Volume (every level
                        Volume..Subclause, Appendix..AppendixArticle),
                        Tables, Figures, machine-readable.
  output/bcbc2024_index.md   - human-readable index, in the same shape as
                        bcbc_mo_index.md: a Summary count table, a
                        Document Level Index per Volume, and Table/Figure
                        indexes.

Usage:
    python3 src/bcbc2024_index.py                     # uses data/<default PDF>
    python3 src/bcbc2024_index.py /path/to/other.pdf   # index a different PDF
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import pymupdf as fitz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "data" / "bcbc_2024.pdf")
JSON_OUT = str(PROJECT_ROOT / "output" / "bcbc2024_index.json")
MD_OUT = str(PROJECT_ROOT / "output" / "bcbc2024_index.md")

# ---------------------------------------------------------------------------
# Bookmark title patterns (checked against `doc.get_toc()` title text, not
# its raw indentation level - see module docstring for why)
# ---------------------------------------------------------------------------

RE_VOLUME = re.compile(r"^Volume\s+([IVXLCDM]+)\s*$")
# `(?:\s+(.*))?$`, not `\s*(.*)$`: the Preface narrates the divisions
# descriptively ("Division A: Compliance, Objectives and Functional
# Statements", "Division B: Acceptable Solutions") - confirmed these are
# NOT real Division headings, just prose mentioning them, and the ":"
# sits directly against the letter with no space before it. Requiring a
# space (or nothing at all) between the letter and any trailing text
# rejects exactly this shape while still matching a real heading, bare
# ("Division B") or with an inline title ("Division A Compliance,
# Objectives and Functional Statements" - a plain space, no colon). Same
# reasoning applied to RE_APPENDIX below, as a precaution.
RE_DIVISION = re.compile(r"^Division\s+([A-Z])(?:\s+(.*))?$")
RE_NOTES_CONTAINER = re.compile(r"^Notes to Part\s+(\d+)\s*(.*)$")
RE_PART = re.compile(r"^Part\s+(\d+)\s*(.*)$")
RE_SECTION = re.compile(r"^Section\s+(\d+\.\d+)\.\s*(.*)$")
RE_ARTICLE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)\.\s*(.*)$")
RE_SUBSECTION = re.compile(r"^(\d+\.\d+\.\d+)\.\s*(.*)$")
RE_APPENDIX = re.compile(r"^Appendix\s+([A-Z])(?:\s+(.*))?$")
# `\s*`, not `\s+`: the bookmark text for every "Section D-N ..." is
# cleanly spaced ("Section D-2 Fire-Resistance Ratings" per the TOC), but
# the same heading's own page rendering, used in Phase 2 to locate its Y
# position, is missing the space for D-2 through D-7 ("Section
# D-2Fire-Resistance Ratings" - confirmed directly; D-1 alone has the
# normal space). Relaxed here so Phase 2 can still find them; harmless for
# Phase 1's clean TOC text, which `\s*` still matches identically to `\s+`.
RE_APPENDIX_PART = re.compile(r"^Section\s+([A-Z])-(\d+)\s*(.*)$")
RE_APPENDIX_ARTICLE = re.compile(r"^([A-Z])-(\d+\.\d+\.\d+)\.\s*(.*)$")
RE_APPENDIX_SECTION = re.compile(r"^([A-Z])-(\d+\.\d+)\.\s*(.*)$")
RE_NOTE_ENTRY = re.compile(r"^([A-Z]-\S+(?:\s+(?:and|to)\s+\(\d+\))*)\s+(.*)$")
# Bare, unnumbered divider headings grouping a block of Part 9's own
# compiled tables - confirmed exactly two, "Fire and Sound Resistance
# Tables" (page 1510) and "Span Tables" (page 1628), same convention (and
# same underlying content) as the MO Package's own TableGroup headings,
# and - like there - entirely unbookmarked, so Phase 1 never sees them at
# all; only Phase 2's page scan can. Left unrecognized, the "9.38.1.1.
# Attributions to Acceptable Solutions" Article open at that point kept
# absorbing everything up to "Notes to Part 9" as its own body - confirmed
# its page length was inflated to 366 pages before this was added.
RE_TABLE_GROUP = re.compile(r"^[A-Z][A-Za-z ]*\bTables\s*$")

# Order matters, exactly as in bcbc_mo_index.py: Article (4-part) must be
# tried before Subsection (3-part), and AppendixArticle (3-part) before
# AppendixSection (2-part) - here more so than there, since bookmark titles
# are clean enough that both the "more specific" and "less specific"
# patterns use a relaxed `\.\s*` separator (bookmark text doesn't have the
# occasional-missing-space quirks raw PDF extraction does), so a shorter
# pattern really could swallow the first segments of a longer number if it
# were ever tried first - classification always stops at the first match,
# so as long as this order is preserved, that never happens.
TOC_PATTERNS = [
    ("Volume", RE_VOLUME),
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
]

# Confirmed directly against this PDF's own bookmark nesting (Appendix C/D
# sit at the same indentation level as Part, both children of Division) -
# unlike bcbc_mo_index.py, which had no bookmark ground truth for the MO
# Package's unbookmarked Appendix C/D and placed them one level shallower
# (sibling of Division) as a best guess. Appendix here mirrors Part's own
# rank exactly, and AppendixPart/AppendixSection/AppendixArticle mirror
# Section/Subsection/Article one-for-one.
RANK = {
    "Volume": 0, "Division": 1,
    "Part": 2, "NotesContainer": 2, "Appendix": 2,
    "Section": 3, "AppendixPart": 3, "TableGroup": 3,
    "Subsection": 4, "AppendixSection": 4,
    "Article": 5, "AppendixArticle": 5,
    "Note": 6,
}
ARTICLE_TYPES = ("Article", "AppendixArticle")


def classify_toc_title(text):
    for ntype, pattern in TOC_PATTERNS:
        m = pattern.match(text)
        if m:
            return ntype, m
    return None


# ---------------------------------------------------------------------------
# Phase 1: build the skeleton from the bookmark outline
# ---------------------------------------------------------------------------

def build_skeleton(doc):
    """Returns (volumes: [node, ...], flat_nodes: [node, ...] in document
    order, heading_lookup: {(page0, bare_number): node}). `bare_number` is
    the plain numeric/letter citation fragment each heading pattern
    captures (e.g. "9.1.1.1." or "D-1.1.1."), used in Phase 2 to relocate
    a heading's own physical line on its page without needing the exact
    title text (bookmark titles and their on-page rendering aren't always
    byte-identical).
    """
    toc = doc.get_toc()
    volumes = []
    flat_nodes = []
    heading_lookup = {}
    stack = []  # (rank, node); empty until the first Volume is seen
    division = None
    in_notes = False

    def bare_number_for(ntype, m):
        if ntype in ("Division", "Appendix"):
            return m.group(1)
        if ntype == "AppendixPart":
            return f"{m.group(1)}-{m.group(2)}"
        if ntype in ("AppendixSection", "AppendixArticle"):
            return f"{m.group(1)}-{m.group(2)}."
        if ntype in ("Section", "Subsection", "Article"):
            return m.group(1) + "."
        if ntype == "Part":
            return m.group(1)
        if ntype == "NotesContainer":
            return m.group(1)
        return None

    for level, text, page in toc:
        text = text.strip()
        page0 = page - 1  # get_toc() pages are already 1-indexed

        # While inside a Notes container, a Note is tried FIRST, before any
        # structural pattern - not after, the way bcbc_mo_index.py orders
        # it (fine there, since its Article/Subsection patterns require a
        # leading digit, never colliding with a Note's leading letter).
        # Here, AppendixArticle/AppendixSection ALSO require a leading
        # letter-hyphen ("D-1.1.1."), the same shape as a Note citation
        # ("A-1.1.1.1.(3)...") - confirmed a real Note's first 3
        # dot-segments satisfy AppendixArticle's own pattern with text left
        # over, so checking structural patterns first was swallowing real
        # Notes as bogus AppendixArticle nodes (873 vs the ~90-100
        # expected, with Note collapsing to near zero) until this was
        # reordered. Genuine structural headings never start with
        # `[A-Z]-`, so this reordering costs nothing there.
        note = None
        if in_notes:
            nm = RE_NOTE_ENTRY.match(text)
            if nm:
                note = nm
        classified = None if note is not None else classify_toc_title(text)
        if classified is None and note is None:
            continue  # noise: Preface, Index, table-row labels, etc.

        if classified is not None:
            ntype, m = classified
            rank = RANK[ntype]
            bare_number = bare_number_for(ntype, m)
            if ntype == "Volume":
                identifier, title = m.group(1), ""
                citation = identifier
            elif ntype == "Division":
                division = m.group(1)
                identifier, title = division, (m.group(2) or "").strip()
                citation = division
            elif ntype == "Part":
                identifier, title = m.group(1), m.group(2).strip()
                citation = f"{division}-{identifier}"
            elif ntype == "NotesContainer":
                identifier, title = m.group(1), m.group(2).strip()
                citation = f"Notes-{division}-{identifier}"
            elif ntype in ("Section", "Article", "Subsection"):
                identifier, title = m.group(1) + ".", m.group(2).strip()
                citation = f"{division}-{identifier}"
            elif ntype == "Appendix":
                identifier, title = m.group(1), (m.group(2) or "").strip()
                citation = f"Appendix-{identifier}"
            elif ntype == "AppendixPart":
                identifier = f"{m.group(1)}-{m.group(2)}"
                title = m.group(3).strip()
                citation = f"Appendix-{identifier}"
            else:  # AppendixSection, AppendixArticle
                identifier = f"{m.group(1)}-{m.group(2)}."
                title = m.group(3).strip()
                citation = f"Appendix-{identifier}"

            new_node = {"type": ntype, "identifier": identifier, "citation": citation,
                        "title": title, "page0": page0, "children": []}

            if ntype == "Volume":
                stack = [(rank, new_node)]
                volumes.append(new_node)
            else:
                while stack and stack[-1][0] >= rank:
                    stack.pop()
                if not stack:
                    # A heading before any Volume bookmark (shouldn't
                    # happen in this PDF - confirmed the very first
                    # Volume bookmark precedes everything else structural)
                    continue
                stack[-1][1]["children"].append(new_node)
                stack.append((rank, new_node))
            flat_nodes.append(new_node)
            if bare_number is not None:
                heading_lookup[(page0, bare_number)] = new_node

            if rank <= 2:
                in_notes = (ntype == "NotesContainer")
            if ntype in ARTICLE_TYPES:
                new_node["_body"] = []
        else:
            identifier = note.group(1).rstrip(".")
            title = note.group(2).strip()
            citation = f"Note:{identifier}"
            new_node = {"type": "Note", "identifier": identifier, "citation": citation,
                        "title": title, "page0": page0, "children": []}
            if stack:
                stack[-1][1]["children"].append(new_node)
            flat_nodes.append(new_node)

    return volumes, flat_nodes, heading_lookup


# ---------------------------------------------------------------------------
# Sentence / Clause / Subclause marker classification (identical approach
# to bcbc_mo_index.py; RE_MARKER alone differs, per the module docstring)
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
# `\)\s*`, not `\)\s+`: confirmed on a full-page sample that this PDF
# consistently has zero space after a marker's closing paren
# ("1)This Code applies...") - a systematic convention here, not an
# occasional PDF-extraction quirk the way it was for the MO Package.
RE_MARKER = re.compile(r"^([A-Za-z0-9]{1,4})\)\s*(.*)$")


def classify_marker(token):
    """'sentence' | 'clause' | 'subclause' | 'ambiguous' | 'noise'."""
    if token.isdigit():
        return "sentence"
    t = token.lower()
    if len(t) == 1:
        return "ambiguous" if t in ROMAN_CHARS else "clause"
    return "subclause" if t in VALID_ROMANS else "noise"


def segment_article_body(body_lines, article_citation):
    """Identical algorithm to bcbc_mo_index.py's function of the same
    name - see there for the full rationale of each rule. body_lines:
    [(page0, y0, x0, text), ...] accumulated for one Article/AppendixArticle.
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
    children = node.get("children", [])
    for i, child in enumerate(children):
        child_end = children[i + 1]["page0"] if i + 1 < len(children) else node_end_page0
        child["end_page0"] = child_end
        finalize_nested_ends(child, child_end)


# ---------------------------------------------------------------------------
# Table/Figure caption detection (same approach as bcbc_mo_index.py, ported
# to this PDF's own fonts: HelveticaLTStd-Bold for captions, confirmed
# distinct from -Blk (headings); no condensed/"Narrow"-equivalent font was
# found on the one multi-page table inspected directly - its own header
# row renders in plain -Roman, not bold at all - so the "stop at first
# non-bold line" rule already excludes it with no extra font exclusion
# needed here, unlike the MO Package's ArialNarrow-Bold table headers.
# ---------------------------------------------------------------------------

RE_CAPTION = re.compile(r"^(Table|Figure)\s+(\S.*)$")
RE_FORMING_PART = re.compile(r"^forming part of\s+(.+)$", re.IGNORECASE)
RE_NOTES_TO_CAPTION = re.compile(r"^notes? to (table|figure)\s*", re.IGNORECASE)
RE_CONTINUED = re.compile(r"\(continued\)\s*$", re.IGNORECASE)


def _page_lines(page):
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


def _consume_while(lines, idx, predicate, max_lines=None):
    parts = []
    while idx < len(lines) and (max_lines is None or len(parts) < max_lines):
        y0, _, text, font = lines[idx]
        if not predicate(text, font, y0, parts):
            break
        parts.append(text)
        idx += 1
    return parts, idx


def _multi_column_rows(page_lines):
    counts = Counter(round(y0, 1) for y0, _x0, _t, _f in page_lines)
    return {y for y, n in counts.items() if n > 1}


# ---------------------------------------------------------------------------
# Phase 2: page-level scan for body text, Sentence/Clause/Subclause, and
# Table/Figure captions
# ---------------------------------------------------------------------------

def scan_pages(doc, heading_lookup):
    """Walks every page. For structural boundaries (needed to know which
    Article/AppendixArticle owns a given body line, and to track the
    innermost open node for `owner_citation`), it looks for the physical
    line of each heading already known (from Phase 1) to start on this
    page - matched by `classify_toc_title` against the page's own
    Helvetica-Blk text, not by rediscovering new headings. Maintains a
    rank-based stack exactly like Phase 1's, rebuilt from these lookups,
    so a TableGroup heading (confirmed unbookmarked - see RE_TABLE_GROUP -
    so it can never come from `heading_lookup`) can still be created on
    the spot and correctly parented under whatever Part is genuinely open
    at that point, then merged into `flat_nodes` afterward by the caller.
    Returns (tables, figures, discovered_nodes) - mutates each
    Article/AppendixArticle node's `_body` in place (via `heading_lookup`'s
    node references).
    """
    tables, figures = [], []
    current_article = None
    root_placeholder = {"citation": "", "children": []}
    stack = [(-1, root_placeholder)]
    discovered_nodes = []

    for pno in range(doc.page_count):
        page_lines = _page_lines(doc[pno])
        row_ys = _multi_column_rows(page_lines)

        idx = 0
        while idx < len(page_lines):
            y0, x0, text, font = page_lines[idx]

            cap_m = RE_CAPTION.match(text)
            if cap_m and "Bold" in font and "Blk" not in font:
                kind = cap_m.group(1)
                title_parts, idx = _consume_while(
                    page_lines, idx + 1,
                    lambda t, f, y, parts: "Bold" in f and "Blk" not in f
                                    and not RE_CAPTION.match(t)
                                    and not RE_FORMING_PART.match(t)
                                    and not RE_NOTES_TO_CAPTION.match(t)
                                    and round(y, 1) not in row_ys,
                    max_lines=2,  # see note above RE_TABLE_GROUP: this PDF's
                    # table header cells are the SAME HelveticaLTStd-Bold as
                    # the caption itself (unlike the MO Package's condensed
                    # "Narrow" headers, there's no font signal here to
                    # exclude them by) - confirmed every genuine title
                    # checked is 1-2 lines, so a 2-line cap (not 3, like the
                    # MO Package) is the backstop bounding header leakage
                    # here.
                )
                forming_part = None
                if idx < len(page_lines):
                    fm = RE_FORMING_PART.match(page_lines[idx][2])
                    if fm:
                        forming_part = fm.group(1).strip()
                        idx += 1
                title = " ".join(title_parts).strip()
                # A continuation page's caption is just the identifier with
                # "(continued)" appended to the SAME line, e.g.
                # "Table 1.1.1.1.(5) (continued)" - confirmed no separate
                # title follows on these pages. Strip the suffix from the
                # identifier (not just check the title, which is empty
                # here) so a continuation shares its base table's own
                # identifier rather than becoming a distinct-looking entry.
                raw_identifier = cap_m.group(2).strip()
                continuation = bool(RE_CONTINUED.search(raw_identifier)) or bool(RE_CONTINUED.search(title))
                identifier = RE_CONTINUED.sub("", raw_identifier).strip()
                entry = {
                    "type": kind, "identifier": identifier,
                    "title": title, "page0": pno,
                    "owner_citation": stack[-1][1]["citation"],
                    "forming_part_of": forming_part,
                    "continuation": continuation,
                }
                (tables if kind == "Table" else figures).append(entry)
                continue

            if "Blk" in font:
                node, newly_discovered = None, False
                classified = classify_toc_title(text)
                if classified is not None:
                    ntype, m = classified
                    bare_number = None
                    if ntype in ("Division", "Appendix"):
                        bare_number = m.group(1)
                    elif ntype == "AppendixPart":
                        bare_number = f"{m.group(1)}-{m.group(2)}"
                    elif ntype in ("AppendixSection", "AppendixArticle"):
                        bare_number = f"{m.group(1)}-{m.group(2)}."
                    elif ntype in ("Section", "Subsection", "Article"):
                        bare_number = m.group(1) + "."
                    elif ntype == "Part":
                        bare_number = m.group(1)
                    elif ntype == "NotesContainer":
                        bare_number = m.group(1)
                    node = heading_lookup.get((pno, bare_number)) if bare_number else None
                elif RE_TABLE_GROUP.match(text):
                    node = {"type": "TableGroup", "identifier": text, "citation": text,
                            "title": "", "page0": pno, "children": []}
                    newly_discovered = True

                if node is not None:
                    rank = RANK[node["type"]]
                    while stack and stack[-1][0] >= rank:
                        stack.pop()
                    if newly_discovered:
                        stack[-1][1]["children"].append(node)
                        discovered_nodes.append(node)
                    stack.append((rank, node))
                    current_article = node if node["type"] in ARTICLE_TYPES else None
                    idx += 1
                    continue

            if current_article is not None:
                current_article["_body"].append((pno, y0, x0, text))
            idx += 1

    return tables, figures, discovered_nodes


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def iter_nodes(node):
    yield node
    for c in node.get("children", ()):
        yield from iter_nodes(c)


def build_index(pdf_path):
    doc = fitz.open(pdf_path)
    last_page0 = doc.page_count - 1

    volumes, flat_nodes, heading_lookup = build_skeleton(doc)
    tables, figures, discovered_nodes = scan_pages(doc, heading_lookup)
    # TableGroup nodes (confirmed unbookmarked, found only by the page
    # scan - see RE_TABLE_GROUP) were already correctly parented into the
    # tree as they were discovered; merge them into flat_nodes by page
    # order too, so page-range finalization (the "next flat_node in
    # document order" rule, same as bcbc_mo_index.py) and the Markdown
    # output see them like any other node.
    flat_nodes = sorted(flat_nodes + discovered_nodes, key=lambda n: n["page0"])

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

    return volumes, flat_nodes, tables, figures


def write_json(volumes, tables, figures, out_path):
    payload = {"volumes": volumes, "tables": tables, "figures": figures}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=1))


def write_markdown(volumes, flat_nodes, tables, figures, out_path):
    lines = ["# bcbc_2024.pdf — Structural Index", ""]

    counts = Counter(n["type"] for n in flat_nodes)
    lines.append("## Summary")
    lines.append("")
    lines.append("| Level | Count |")
    lines.append("|---|---|")
    for level in ("Volume", "Division", "Part", "NotesContainer", "Note", "Section", "Subsection",
                  "Article", "Appendix", "AppendixPart", "AppendixSection", "AppendixArticle",
                  "TableGroup"):
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

    lines.append("## Document Level Index (Volume → Article/AppendixArticle, Notes to Part → Note)")
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

    for volume in volumes:
        walk(volume, 0)
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
    volumes, flat_nodes, tables, figures = build_index(pdf_path)

    write_json(volumes, tables, figures, JSON_OUT)
    write_markdown(volumes, flat_nodes, tables, figures, MD_OUT)

    c = Counter(n["type"] for n in flat_nodes)
    print("Counts:", file=sys.stderr)
    for t, n in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {t}", file=sys.stderr)
    print(f"  {len(tables):6d}  Table", file=sys.stderr)
    print(f"  {len(figures):6d}  Figure", file=sys.stderr)
    print(f"Wrote {JSON_OUT} and {MD_OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
