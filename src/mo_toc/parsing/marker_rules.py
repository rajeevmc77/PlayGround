"""Classifies the bracketed markers ("1)", "a)", "iv)") that mark Sentence/
Clause/Subclause boundaries in an Article's body text. A single roman-shaped
letter (i, v, x, l, c, d, m) is inherently ambiguous between "clause" and
"subclause" out of context — resolving it is the segmenter's job (see
tree_builder.py), not this module's.
"""

import re

ROMAN_CHARS = set("ivxlcdm")
RE_MARKER = re.compile(r"^([A-Za-z0-9]{1,4})\)\s+(.*)$")
_RE_GLUED_MARKER = re.compile(r"^([A-Za-z0-9]{1,4})\)(\S.*)$")


_ROMAN_VALUES = [
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
]


def to_roman(number: int) -> str:
    remaining, symbols = number, ""
    for value, symbol in _ROMAN_VALUES:
        while remaining >= value:
            symbols += symbol
            remaining -= value
    return symbols


def _valid_romans(limit: int = 60) -> set[str]:
    return {to_roman(n) for n in range(1, limit + 1)}


VALID_ROMANS = _valid_romans()


def classify_marker(token: str) -> str:
    if token.isdigit():
        return "sentence"
    lowered = token.lower()
    if len(lowered) == 1:
        return "ambiguous" if lowered in ROMAN_CHARS else "clause"
    return "subclause" if lowered in VALID_ROMANS else "noise"


def match_marker(text: str, runs: tuple = ()) -> re.Match | None:
    """A line's leading "1)"/"a)"/"iv)" marker. Where the PDF set the marker
    as its own span, the space after it can be a whitespace-only span the
    text leaves out ("3)For the purpose ..."): the marker's own span ending
    at its ")" still makes it one - `runs` are the line's (start, end, x0, x1)
    per span - if it is a marker's shape."""
    match = RE_MARKER.match(text)
    if match or not runs:
        return match
    glued = _RE_GLUED_MARKER.match(text)
    own_span = glued is not None and runs[0][1] == glued.end(1) + 1
    return glued if own_span and classify_marker(glued.group(1)) != "noise" else None
