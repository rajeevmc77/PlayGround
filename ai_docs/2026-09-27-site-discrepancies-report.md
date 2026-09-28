# BCBC Site Discrepancies

Where the BC Building Code website differs from the signed PDF.

- **Compared:** every provision, table cell, note and clause of the signed MO package PDF
  (`data/MO Package BCBC MRK signed.pdf`) against the same content on the website.
- **Website:** `dev.buildingcode.gov.bc.ca`, version 2024, content as of 2024-03-08
  (`output/web_source/snapshot.json`).
- **Comparison run:** 2026-09-27, from `main` at PR #73. Inputs are `output/bcbc_pdf.json`,
  `output/bcbc_web.json` and `output/comparison.json`.
- **Published copy:** https://claude.ai/artifact/LGAkkPDTsua3hUF5CZutnp

This report lists the differences that come from the website: how it renders references, standards,
punctuation and formatting, and where its data or structure differs from the PDF. Each item has a
count, where it concentrates, real examples, and a suggested fix. The last section lists the few
remaining differences that come from our own PDF extraction.

In the examples, `PDF:` is the signed PDF's text and `Site:` is the website's.

## Summary

| | |
|---|---|
| Items compared | 94,122 |
| Items that match | 82,706 (87.9%) |
| Text items that differ | 5,888 |

An item matches when its text is identical apart from spacing and its bold and italic match. No
other styling is compared (see `2026-09-26-compare-emphasis-design.md`). Containers such as articles
and tables fail when any item inside them differs, so the 5,888 text items (cells, sentences,
clauses, notes) are the ones to look at. Each one is counted in exactly one row below.

| Kind of difference | Items | Concentrated in |
|---|---:|---|
| **Formatting** | **1,988** | |
| Bold in the PDF's tables is plain on the site | 1,702 | 9.38.1.1., 3.10.1.1., 4.5.1.1., 6.10.1.1., 5.10.1.1., 8.3.1.1. |
| Italic differs, and mixed bold/italic | 286 | Appendix D, Spec Tables, 4.1.8.11. |
| **Cross-references** | **615** | |
| Reference words repeated ("to Article …") | 349 | 3.10.1.1., Parts 3 and 9 |
| Note references rewritten or cut short | 266 | 1.3.1.2., A-Table 9.23.3.5.-B, A-9.36.2.x |
| **Standards and punctuation** | **964** | |
| Standard designations changed | 477 | 5.9.1.1., 9.36.3.10., throughout Parts 3 and 9 |
| Punctuation moved or dropped | 466 | 5.9.1.1., Appendix D, 3.8.3.1. |
| Letter case in standard titles | 21 | 5.8.1.4., 5.8.1.5. |
| **Missing or different content** | **611** | |
| No matching item on the site | 347 | 1.3.1.2., 9.38.1.1., Spec Table 1 |
| Site cell holds an image description | 228 | Spec Table 1, 9.23.13.11., A-9.11.1.4. |
| Site cell is empty | 36 | Spec Table 2, 9.23.13.7., 9.38.1.1. |
| **Other wording** (not classified automatically) | **1,710** | Spec Table 1, 1.3.1.2., 9.38.1.1. |

### Accepted as matches since this run (2026-09-28)

The counts above are from the 2026-09-27 run. Since then the comparison accepts these typing and
punctuation differences as matches, so they no longer fail (`src/shared/styled_text.py`). The
matching items rose to 83,211 of 94,122 (88.4%).

| Difference | PDF | Site | Items that now match |
|---|---|---|---:|
| Typed dashes | `Documents—the`, `Systems – Maximum` | `Documents---the`, `Systems -- Maximum` | 24 |
| Unit multiplication dot | `kWh/(m²•year)` | `kWh/(m²·year)` | 35 |
| Comma or period at a closing quote | `"Wood preservation," and`, `Systems."` | `"Wood preservation" and`, `Systems".` | 409, with the next row |
| A cited number's final period | `3.2.4.8., 3.2.4.9.`, `Subsection 9.10.9. 2 h` | `3.2.4.8 , 3.2.4.9`, `Subsection 9.10.9 . 2 h` | (see above) |

The PDF's own "•" before list items is ignored too (37 items). That one was on our side, since the
site renders the same lists as bullets that aren't text.

## Structure and data

### Sections 3.9 and 3.10 are swapped

The site files the PDF's Section 3.9 content under 3.10 and the reverse, down to article level. Its
headings and titles are swapped too, so every provision in both sections sits under the wrong number.

| PDF | Site |
|---|---|
| Section 3.9. Self-service Storage Buildings | 3.9 Objectives and Functional Statements |
| Section 3.10. Objectives and Functional Statements | 3.10 Self-service Storage Buildings |
| 3.9.1.1. Definition | 3.9.1.1 Attributions to Acceptable Solutions |

**Suggested fix:** renumber the two sections in the site's source data.

### Table C-2 is the national table, not BC's

The PDF's Table C-2 (climatic design data) has 120 rows. It lists British Columbia locations only,
ending at Youbou. The site's table has 709 rows: it continues with Alberta, Ontario, Quebec, Yukon,
Nunavut and the rest of Canada.

**Suggested fix:** confirm which table the BC code should publish. If it's the BC one, trim the site's
table to BC locations.

### Table 5.9.1.1. combines columns (about 190 cells)

The PDF gives the issuing body, document number and title separate columns. The site repeats a
combined string in each of those cells.

- PDF (two cells): `A135.6` | `Engineered Wood Siding`
- Site (both cells): `ANSI A135.6, "Engineered Wood Siding"`

**Suggested fix:** render each column from its own field.

### Clause letters out of order (example: 3.1.9.4.(4))

The site shows the right clauses under the wrong letters. Other clauses cite them by letter, so
readers are sent to the wrong clause.

| PDF | Site |
|---|---|
| (a) except as provided in Clause (b), the piping is sealed … | c) except as provided in Clause (b), the piping is sealed … |
| (b) in buildings more than 3 storeys in building height … | a) in buildings more than 3 storeys in building height … |
| (c) the piping is not located in a vertical service space. | b) the piping is not located in a vertical service space. |

**Suggested fix:** check the clause order in the source data for this sentence and any like it.

### Table notes printed inside cells (mainly Spec Table 1)

Where the PDF puts a note marker such as (6) in a cell, the site pastes the note's whole text into
the cell.

- PDF: `W13 with • 89 mm thick absorptive material on each side(6)(13) …`
- Site: `W13 with • 89 mm thick absorptive material on each sideWhere bracing material, such as diagonal lumber or plywood, OSB, gypsum board or fibr…`

**Suggested fix:** render note references as markers linking to the table's notes.

## Formatting

### Bold in the PDF's tables is plain on the site (1,702 items)

These items are in 9.38.1.1. (854), 3.10.1.1. (421), 4.5.1.1. (125), 6.10.1.1. (53), 5.10.1.1. (33)
and 8.3.1.1. (22), plus header cells elsewhere.

The objectives and functional statements tables bold each provision heading, and many other tables
bold their header rows. The site renders these cells in plain text. The words match; only the weight
differs.

- PDF (Table 9.38.1.1.): **9.3.1.1. General**
- Site: 9.3.1.1. General

**Suggested fix:** apply the bold style to heading rows in these tables (a template change, not a
content edit).

### Italic differs (35 items italic only, 251 mixed bold and italic)

The site italicises defined terms in places where the PDF sets them in roman, and the reverse. In
Table 9.23.13.7.-D, for example, the PDF sets "Storey" in the regular face (ArialNarrow, checked in
the PDF itself). The site italicises it as a defined term.

- PDF: Storey supporting roof only
- Site: *Storey* supporting roof only

**Suggested fix:** decide whether the site's defined-term styling should follow the PDF inside tables.

## Cross-references

The site generates reference text from links instead of printing the PDF's wording. That produces
two kinds of error: repeated reference words, and references that lose part of their number. The
losses matter more, because the reader can no longer tell what is being referenced.

### Reference words repeated (349 items)

In a range or list, the site repeats the reference type before every number.

- PDF (3.1.2.1.(1)): `Except as permitted by Articles 3.1.2.3. to 3.1.2.5., and 3.1.2.7., every building …`
- Site: `Except as permitted by Articles 3.1.2.3. to Article 3.1.2.5. , and Article 3.1.2.7. , every building …`

- PDF (3.1.6.14.(3)): `Except as provided in Sentences (4) and 3.1.6.4.(3) and (6), …`
- Site: `Except as provided in Sentences (4) and 3.1.6.4.(3) and 3.1.6.4.(6) , …`

### References that lose part of their number

These patterns overlap with other categories, so each count is the number of items showing that
pattern.

| Pattern | Items |
|---|---:|
| Article number dropped, almost all in the "Code reference" column of Table 1.3.1.2. (Documents Referenced), which keeps only the sentence number | 288 |
| Table or figure letter dropped ("Table 3.2.3.1.-A" becomes "Table 3.2.3.1.") | 118 |
| Note reference cut to "Note B-n." | 95 |
| Clause reference shortened ("Subclause (1)(b)(i)" becomes "Subclause (i)") | 11 |
| Raw reference code shown instead of text | 6 |

"Note" is also added before A-numbers in most of the 266 items in this category.

Examples:

- PDF (Table 1.3.1.2.): `3.6.5.4.(4) 3.6.5.5.(1) 9.33.6.4.(4) 9.33.8.2.(2)`
- Site: `(4) (1) (4) (2)`

- PDF (3.1.5.5.(2)): `… the limiting distance in Tables 3.2.3.1.-B to 3.2.3.1.-E permits …`
- Site: `… the limiting distance in Tables 3.2.3.1. to Table 3.2.3.1. permits …`

- PDF (3.2.5.12.(10)): `(See Note A-3.2.5.12.(10).)`
- Site: `(See Note B-3.)`

- PDF (3.1.5.6.(2)): `… deemed to comply with Subclause (1)(b)(i).`
- Site: `… deemed to comply with Subclause (i).`

- PDF (Table 9.23.11.4.-A): `Heavyweight construction(4)`
- Site: `Heavyweight Construction[REF:table-note:nbc.divBV2.part9.sect23.subsect11.art4.table1.note4]`

**Suggested fix:**
- Print the full target number for every reference, including the table or figure letter and the
  article number.
- Print note references as "Note A-…" with the note's own number.
- Treat any unresolved reference code as a publishing error.

## Standards and punctuation

### Standard designations changed (477 items)

The site adds the issuing body in front of the designation, and sometimes an edition year, where the
PDF prints the designation alone.

- PDF (3.1.5.7.(1)(b)(ii)): `when tested in accordance with CAN/ULC-S138, "Standard Method of Test …`
- Site: `when tested in accordance with ULC CAN/ULC-S138, "Standard Method of Test …`

- PDF (1.4.1.2.(1)): `… acceptance criteria of CAN/ULC-S114, "Standard Method …`
- Site: `… acceptance criteria of ULC CAN/ULC-S114:2018, "Standard Method …`

- PDF (D-1.5.1.(1)(a)): `CAN/CSA A82.27-M, "Gypsum Board," or`
- Site: `CSA CAN/CSA A82.27-M91, "Gypsum Board" or`

**Suggested fix:** print the designation exactly as the code does. If edition years are wanted, they
belong in Table 1.3.1.2.

### Punctuation moved or dropped (466 items)

The site moves commas and periods outside closing quotation marks, drops trailing commas and periods,
and adds periods after some section numbers.

| Provision | PDF | Site |
|---|---|---|
| 3.2.4.19.(5)(b) | `… Fire Alarm Systems."` | `… Fire Alarm Systems".` |
| 1.3.3.3.(1)(a) | `reserved,` | `reserved` |
| 1.2.1.1.(1)(b) | `… under Section 2.3 of Division C, …` | `… under Section 2.3. of Division C, …` |

### Letter case in standard titles (21 items)

- PDF (5.8.1.4.(1)): `"Building Acoustics – Estimation of Acoustic Performance of Buildings …`
- Site: `"Building acoustics – Estimation of acoustic performance of buildings …`

## Missing or different content

### No matching item on the site (347 items)

These items are in 1.3.1.2. (104), 9.38.1.1. (40), Spec Table 1 (24), 9.10.16.2. (10),
A-9.11.1.4. (10) and Appendix D (about 30).

The PDF has these rows, cells or clauses and the site has nothing at that place:
- In Table 1.3.1.2., whole document rows (e.g. some AAMA and CCBFC entries) have no site row.
- In Appendix D, some subclauses (i), (ii) aren't broken out in the site's data.
- Items in the 3.9/3.10 swap also land here.

### Site cell holds an image description (228 items)

Where the PDF shows a drawing in a table cell, the site's cell holds the image's description as text,
e.g. "Single storey building configuration" in Table 9.23.13.11.-B. The PDF cell has no text, so it
can't match. This is expected and probably fine, but it inflates the count.

### Site cell is empty (36 items)

For example, the header cell "Concrete or Concrete Block, mm" in Table 9.15.4.2. is empty on the site.

### Other wording (1,710 items)

These items are in Spec Table 1 (265), 1.3.1.2. (249), 9.38.1.1. (127) and 9.23.13.7. (46), with
fewer than 25 in each other provision.

Their differences don't fit one pattern above. Most combine several of the patterns in one item.
Others differ in the provision numbers they cite, which looks like content from a different edition:

- PDF (Table 1.1.1.1.(5)): `Dead-end Corridors Sentence 3.3.1.9.(7), Article 9.9.7.3. …`
- Site: `Dead-end Corridors Sentence 3.3.1.9.(5) , Article 9.9.7.3 . …`

- PDF (3.2.5.6.(2)): `… Sentence 3.2.2.10.(1) shall be more than …`
- Site: `… Sentence 3.2.2.10.(3) shall be more than …`

**Suggested fix:** check these cited numbers against the signed code first. They change meaning,
unlike the formatting items.

## What is not the site's

A few remaining differences come from how we read the PDF. They are listed here so they aren't
reported as site problems:

- **About 40 cells in Tables 9.23.13.7.-B and -D.** The PDF draws no line between some sub-rows, so
  our extraction keeps them in one row where the site has several.
- **Bulleted list items in notes and tables.** The PDF prints the "•" as text, while the site draws
  its bullets with styling. About 360 items carry a bullet; for most of them, it isn't the only
  difference.
- **One blank row in Table 1.1.1.1.(5).** A stray rule in the PDF splits a cell, which shifts the rows
  around row 14.
- **An unknown share of the 1,710 "other wording" items** may include extraction errors that weren't
  reviewed one by one.

Everything else above was checked against the PDF's own text, fonts or table rules. Counts come from
the automated comparison and were sorted by pattern; an item appears in exactly one row of the
summary table.
