# Compare: text + bold/italic, whitespace-normalised

## Rule

A PDF leaf node (Sentence, Clause, Subclause, Cell) and its web counterpart
(joined on `unified_number`) match when:

1. their text is identical once **all whitespace is dropped**. The PDF breaks
   lines inside words and citations ("fire- resistance", "A- 1.1.1.1."), where
   the web doesn't. Anything else, case and punctuation glyphs included, has to
   match exactly.
2. every **letter and digit** is in the same style on both sides: plain, bold,
   italic or bold-italic. How punctuation is styled is ignored (e.g. whether
   the comma after an italic term is italic too).

No other formatting counts: font family, size, colour, wrapping and layout are
all ignored. This replaces the old 80% `SequenceMatcher` text score. The
`--threshold-percent` flag now applies to images only.

The web shows a sentence/clause/subclause with its own "1)"/"a)"/"i)" marker in
front, while the PDF pipeline has already cut it off. So the web's leading
marker is dropped before comparing, but only when it is that node's own.

## Data

Both indexes now give each content node an `emphasis` list alongside `content`:
`[start, end, style]` character ranges into `content`, with `style` one of
`"b"`, `"i"`, `"bi"`. Unstyled text has no range. `shared/styled_text.py`
(`StyledText`) builds, joins and slices these ranges and holds the `matches`
rule.

- **PDF** (`mo_toc/parsing/pdf_source.py`): a span's style comes from its font
  name (`Bold`/`Black`/`Heavy`/`Semibold`/`Demi`, `Italic`/`Oblique`) or its
  PyMuPDF flags (bold 16, italic 2). The font name is needed because
  Arial-Black renders heavy without setting the bold flag. The ranges follow
  the text as the body segmenter joins continuation lines and cuts markers,
  and as table cells join their lines.
- **Web** (`web_toc/parsing/layout_script.py`): the layout pass reads each text
  run's computed `font-weight` (≥ 600 counts as bold) and `font-style`, with
  `::before`/`::after` content included. Measuring the computed style picks up
  CSS-only styling such as the italic `glossary-term` spans. `layout_join`
  copies `emphasis` onto every node whose text it takes from the layout.

## Rebuild

```bash
python src/build_web_pages.py --measure-only   # offline: re-measure layouts with emphasis
python src/build_web_toc.py
python src/build_mo_toc.py
python src/build_comparison.py
```
