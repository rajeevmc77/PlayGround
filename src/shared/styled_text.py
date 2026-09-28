"""Text plus its bold/italic ranges - the only formatting the PDF-vs-web
comparison checks. Both pipelines record a node's `content` together with
`emphasis`: [start, end, style] character ranges into that content, style
"b", "i" or "bi" (unstyled text has no range).

`matches` is the comparison rule: the two texts must be identical once all
whitespace is dropped (the PDF breaks lines inside words and citations -
"fire- resistance", "A- 1.1.1.1." - where the web doesn't), and the "•" the
PDF prints before list items with it; the site's typed "---"/"--" read as the
dash they stand for, and a comma or period at a closing quote or a cited
number's final period (which the site leaves out) don't count; and every
letter and digit must carry the same bold/italic on both sides. Punctuation's
own styling is ignored: whether the comma after an italic term is italic too
isn't visible enough to matter. Pure: no PDF, browser or file I/O.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

STYLES = frozenset({"b", "i", "bi"})

# Typographic variants read as the same character: the PDF typesets curly
# quotes “ ” ‘ ’ where the web often has plain " and ', and – — − (en dash,
# em dash, minus) and non-breaking/typographic hyphens where it has "-"; and
# both sides mix superscript digits with plain ones ("kg/m²", "kg/m2").
_PLAIN_CHARACTERS = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # minus sign
        "¹": "1",
        "²": "2",
        "³": "3",
    }
)

# A bulleted list's bullet: the PDF prints it as text, the site renders the
# list as <ul> items whose bullets are not text. The PDF prints a unit's
# multiplication dot with the same "•" ("kWh/(m²•year)") where the site
# writes "·" or "⋅", so no dot glyph counts.
_DOTS = frozenset("•·⋅")

# A cited number: "3.2.4.8", "9.38", or lettered - "D-6", "A-9.36.2.4" - with
# any Sentence/Clause brackets after it: "D-2.3.9.(2)", "3.2.4.1.(2)(a)" - the
# site sometimes spaced apart: "A-2.2.7.2.(1) (b)".
_CITED_NUMBER = (
    r"(?:(?<![A-Za-z])[A-Z]-\d+(?:\.\d+)*|\d+(?:\.\d+)+)"
    r"(?:\.?\([0-9a-z]+\)(?:\s*\([0-9a-z]+\))*)?"
)

# Characters the site leaves out or types differently, each pattern's group 1
# the characters that don't count:
_UNCOUNTED = (
    # A typed dash reads as the one dash it stands for: the site types "---"
    # for an em dash and "--" for an en dash where the PDF typesets — and –.
    re.compile(r"-(-{1,2})"),
    # A comma or period at a closing quote: the PDF puts a standard title's
    # inside it (“Wood preservation,”), the site leaves it out or moves it
    # outside ("Wood preservation" / "Fire Alarm Systems".). A curly ” always
    # closes; a plain " closes when it follows a non-space.
    re.compile(r'(?<=[^\s“"])([.,])(?=\s*”|")'),
    re.compile(r'(?:”|(?<=\S)")([.,])'),
    # A cited number's final period, which the site drops or prints apart
    # after its cross-reference link: "3.2.4.8, 3.2.4.9", "(3.8.3.2)",
    # "Subsection 9.10.9 . 2 h" where the PDF has "3.2.4.8.", "(3.8.3.2.)",
    # "9.10.9. 2 h" - and "Section D-6. of", "Sentence D-2.3.9.(2). by way"
    # where the PDF has "D-6 of", "D-2.3.9.(2) by way" - but
    # not the period right before a Sentence's "(1)", nor one followed by a
    # digit, where the PDF breaks a line inside the number ("3.2 .4.9.").
    re.compile(_CITED_NUMBER + r"(\.)(?![\d(])"),
    re.compile(_CITED_NUMBER + r"\s+(\.)(?!\d)"),
)

Range = tuple[int, int, str]


def _is_compared(char: str) -> bool:
    return not char.isspace() and char not in _DOTS


def _uncounted(text: str) -> set[int]:
    return {
        i
        for pattern in _UNCOUNTED
        for match in pattern.finditer(text)
        for i in range(match.start(1), match.end(1))
    }


def compared_positions(text: str) -> list[int]:
    """Where the characters that count in the comparison sit in `text`: not
    whitespace, not a bullet or dot, and none of the _UNCOUNTED ones."""
    uncounted = _uncounted(text)
    return [i for i, char in enumerate(text) if _is_compared(char) and i not in uncounted]


def style_of(bold: bool, italic: bool) -> str:
    return ("b" if bold else "") + ("i" if italic else "")


def _merge_touching(ranges: Iterable[Range]) -> tuple[Range, ...]:
    merged: list[Range] = []
    for start, end, style in ranges:
        if merged and merged[-1][1] == start and merged[-1][2] == style:
            merged[-1] = (merged[-1][0], end, style)
            continue
        merged.append((start, end, style))
    return tuple(merged)


def _clip(ranges: Iterable[Range], start: int, end: int) -> tuple[Range, ...]:
    """The parts of `ranges` inside [start, end), re-based to start at 0."""
    clipped = ((max(s, start) - start, min(e, end) - start, style) for s, e, style in ranges)
    return tuple(r for r in clipped if r[0] < r[1])


@dataclass(frozen=True)
class StyledText:
    text: str
    emphasis: tuple[Range, ...] = ()

    def __post_init__(self):
        unknown = {style for _, _, style in self.emphasis} - STYLES
        if unknown:
            raise ValueError(f"unknown emphasis style(s): {sorted(unknown)}")

    @classmethod
    def from_runs(cls, runs: Iterable[tuple[str, str]]) -> "StyledText":
        """Concatenates (text, style) runs, then strips outer whitespace."""
        text, ranges = "", []
        for run_text, style in runs:
            if style and run_text:
                ranges.append((len(text), len(text) + len(run_text), style))
            text += run_text
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        return cls(text[start:end], _clip(_merge_touching(ranges), start, end))

    @classmethod
    def from_json(cls, text: str, emphasis: list | None) -> "StyledText":
        return cls(text or "", tuple((s, e, style) for s, e, style in emphasis or []))

    def emphasis_json(self) -> list[list]:
        return [list(r) for r in self.emphasis]

    def join(self, other: "StyledText") -> "StyledText":
        """`self` and `other` separated by one space, as prose lines join."""
        if not other.text:
            return self
        if not self.text:
            return other
        offset = len(self.text) + 1
        shifted = ((s + offset, e + offset, style) for s, e, style in other.emphasis)
        return StyledText(f"{self.text} {other.text}", self.emphasis + tuple(shifted))

    def slice(self, start: int) -> "StyledText":
        return StyledText(self.text[start:], _clip(self.emphasis, start, len(self.text)))

    def between(self, start: int, end: int) -> "StyledText":
        return StyledText(self.text[start:end], _clip(self.emphasis, start, end))

    def signature(self) -> list[tuple[str, str]]:
        """(character, style) for every compared character (see
        compared_positions), curly quotes and dashes made plain; the style
        only counts on letters and digits."""
        styles = [""] * len(self.text)
        for start, end, style in _clip(self.emphasis, 0, len(self.text)):
            styles[start:end] = [style] * (end - start)
        plain = self.text.translate(_PLAIN_CHARACTERS)
        return [
            (plain[i], styles[i] if plain[i].isalnum() else "")
            for i in compared_positions(self.text)
        ]


def matches(a: StyledText, b: StyledText) -> bool:
    return a.signature() == b.signature()
