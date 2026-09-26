"""Text plus its bold/italic ranges - the only formatting the PDF-vs-web
comparison checks. Both pipelines record a node's `content` together with
`emphasis`: [start, end, style] character ranges into that content, style
"b", "i" or "bi" (unstyled text has no range).

`matches` is the comparison rule: the two texts must be identical once all
whitespace is dropped (the PDF breaks lines inside words and citations -
"fire- resistance", "A- 1.1.1.1." - where the web doesn't), and every letter
and digit must carry the same bold/italic on both sides. Punctuation's own
styling is ignored: whether the comma after an italic term is italic too
isn't visible enough to matter. Pure: no PDF, browser or file I/O.
"""

from collections.abc import Iterable
from dataclasses import dataclass

STYLES = frozenset({"b", "i", "bi"})

Range = tuple[int, int, str]


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

    def signature(self) -> list[tuple[str, str]]:
        """(character, style) for every non-whitespace character; the style
        only counts on letters and digits."""
        styles = [""] * len(self.text)
        for start, end, style in _clip(self.emphasis, 0, len(self.text)):
            styles[start:end] = [style] * (end - start)
        return [
            (char, style if char.isalnum() else "")
            for char, style in zip(self.text, styles, strict=True)
            if not char.isspace()
        ]


def matches(a: StyledText, b: StyledText) -> bool:
    return a.signature() == b.signature()
