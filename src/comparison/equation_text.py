"""Compares an equation by its text: the PDF's formula image as OCR reads it
(formula_ocr.py) against the site's own formula text, its MathJax alt text.

A pixel comparison can't match the PDF's typewriter-set formulas with the
site's MathJax renders, but where OCR reads a formula well its letters and
digits match the site's. Only letters and digits are compared - OCR reads
"×" as "x", "−" as "—", and loses superscripts and fraction bars. Measured on
every paired equation, a reading this close to the site's text never came
from a different formula in the same provision; stacked fractions and sums
read as noise, and those stay with the pixel comparison.

The site renders a command MathJax doesn't know as "[f]" or "[a]" in front
of the formula, shown to readers - a formula the PDF doesn't have. Pure."""

import re
from difflib import SequenceMatcher

MATCHING_TEXT = 0.7  # of the letters and digits, in order
_MATHJAX_ERROR = re.compile(r"\[[a-z]\]")
_NOT_COMPARED = re.compile(r"[^0-9a-z]")


def _letters_and_digits(text: str) -> str:
    return _NOT_COMPARED.sub("", text.lower())


def formula_text_matches(ocr_text: str, site_text: str) -> bool:
    read, shown = _letters_and_digits(ocr_text), _letters_and_digits(site_text)
    if not (read and shown):
        return False
    return SequenceMatcher(None, read, shown, autojunk=False).ratio() >= MATCHING_TEXT


def shows_mathjax_error(site_text: str) -> bool:
    return bool(_MATHJAX_ERROR.search(site_text))
