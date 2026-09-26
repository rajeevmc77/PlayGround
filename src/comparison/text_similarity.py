"""Word-level text similarity between a PDF node's own rendered content and
its web counterpart's - the same content, extracted by two independent
pipelines, should read as near-identical prose even where whitespace,
punctuation spacing, or minor OCR/markup artifacts differ."""

import re
from difflib import SequenceMatcher

DEFAULT_THRESHOLD_PERCENT = 80.0


def _normalize(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    # The PDF and web extraction pipelines disagree on whether a citation
    # like "3.2.8." gets a stray space before its trailing punctuation -
    # cosmetic noise, not a real content difference.
    return re.sub(r"\s+([.,;:)])", r"\1", collapsed)


def similarity_percent(a: str, b: str) -> float:
    a_norm, b_norm = _normalize(a), _normalize(b)
    if not a_norm and not b_norm:
        return 100.0
    return round(SequenceMatcher(None, a_norm, b_norm).ratio() * 100, 1)


def matches(a: str, b: str, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT) -> bool:
    return similarity_percent(a, b) >= threshold_percent
