"""Classifies the bracketed markers ("1)", "a)", "iv)") that mark Sentence/
Clause/Subclause boundaries in an Article's body text. A single roman-shaped
letter (i, v, x, l, c, d, m) is inherently ambiguous between "clause" and
"subclause" out of context — resolving it is the segmenter's job (see
tree_builder.py), not this module's.
"""

import re

ROMAN_CHARS = set("ivxlcdm")
RE_MARKER = re.compile(r"^([A-Za-z0-9]{1,4})\)\s+(.*)$")


def _valid_romans(limit: int = 60) -> set[str]:
    values = [
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
    romans = set()
    for n in range(1, limit + 1):
        remaining, symbols = n, ""
        for value, symbol in values:
            while remaining >= value:
                symbols += symbol
                remaining -= value
        romans.add(symbols)
    return romans


VALID_ROMANS = _valid_romans()


def classify_marker(token: str) -> str:
    if token.isdigit():
        return "sentence"
    lowered = token.lower()
    if len(lowered) == 1:
        return "ambiguous" if lowered in ROMAN_CHARS else "clause"
    return "subclause" if lowered in VALID_ROMANS else "noise"
