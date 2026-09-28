"""Why a PDF item's text and its web counterpart's don't match, for the
viewer to show beside a failed item: the stretches of text that differ, each
with a little context either side and the kind of difference it is, or - when
the words are the same - which words' bold/italic differ.

Texts are compared the way the match rule compares them (StyledText.signature:
whitespace and list bullets dropped, curly quotes and dashes made plain), and each differing
stretch is mapped back to the original text so it reads normally. Pure: no
file or browser I/O."""

import difflib
import re

from shared.styled_text import StyledText, is_compared

CONTEXT = 30  # characters of unchanged text shown either side of a change
MAX_EDITS = 3
_STYLE_NAMES = {"": "plain", "b": "bold", "i": "italic", "bi": "bold italic"}

# What each kind of difference looks like once whitespace is dropped.
_PUNCTUATION = re.compile(r"[.,;:\"'()]+")
_REFERENCE = re.compile(
    r"(Sentences?|Articles?|Clauses?|Subclauses?|Tables?|Figures?|Subsections?|Sections?"
    r"|Parts?|ofDivision[ABC]|(\d+\.)+(\(\w+\))*|-[A-Z])+"
)
_STANDARD = re.compile(r"(ULC|CSA|CGSB|ASTM|ANSI|UL|NFPA|CCBFC|NRCC|ISO|IEC|:\d{2,4})+")


def _replaced_category(pdf_part: str, web_part: str) -> str:
    if pdf_part.lower() == web_part.lower():
        return "Letter case"
    return "Note link text" if "Note" in web_part else "Wording"


_ONE_SIDED = (
    ("Punctuation", _PUNCTUATION),
    ("Reference wording", _REFERENCE),
    ("Standard designation", _STANDARD),
)


def _one_sided_category(changed: str) -> str:
    """Text only one side has."""
    name = next((name for name, pattern in _ONE_SIDED if pattern.fullmatch(changed)), None)
    return name or ("Note link text" if changed == "Note" else "Wording")


def _category(pdf_part: str, web_part: str) -> str:
    if pdf_part and web_part:
        return _replaced_category(pdf_part, web_part)
    return _one_sided_category(pdf_part or web_part)


def _positions(text: str) -> list[int]:
    """Where each signature character sits in the original text."""
    return [i for i, char in enumerate(text) if is_compared(char)]


def _text_span(positions: list[int], text: str, start: int, end: int) -> tuple[int, int]:
    """Signature characters [start, end) as a stretch of the original text; an
    empty stretch sits just after the character before it."""
    if end > start:
        return positions[start], positions[end - 1] + 1
    point = positions[start - 1] + 1 if start > 0 else 0
    return point, point


def _sides(text: str, start: int, end: int) -> list[str]:
    """[before, changed, after], the context trimmed to CONTEXT characters."""
    before = ("…" if start > CONTEXT else "") + text[max(0, start - CONTEXT) : start]
    after = text[end : end + CONTEXT] + ("…" if end + CONTEXT < len(text) else "")
    return [before, text[start:end], after]


def _edit(pdf: str, web: str, opcode, signatures: tuple[str, str]) -> dict:
    _tag, i1, i2, j1, j2 = opcode
    pdf_span = _text_span(_positions(pdf), pdf, i1, i2)
    web_span = _text_span(_positions(web), web, j1, j2)
    return {
        "category": _category(signatures[0][i1:i2], signatures[1][j1:j2]),
        "pdf": _sides(pdf, *pdf_span),
        "web": _sides(web, *web_span),
    }


def _text_reason(pdf: str, web: str, signatures: tuple[str, str]) -> dict:
    matcher = difflib.SequenceMatcher(None, *signatures, autojunk=False)
    opcodes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    edits = [_edit(pdf, web, op, signatures) for op in opcodes]
    categories = {edit["category"] for edit in edits}
    category = categories.pop() if len(categories) == 1 else "Mixed"
    return {
        "kind": "text",
        "category": category,
        "edit_count": len(edits),
        "edits": edits[:MAX_EDITS],
    }


def _only_punctuation(signature: list, start: int, end: int) -> bool:
    return all(not signature[k][0].isalnum() for k in range(start, end))


def _style_runs(pdf_sig: list, web_sig: list) -> list[tuple[int, int, str, str]]:
    """(start, end, pdf style, web style) for each stretch of signature whose
    bold/italic differs, joined across the punctuation between words."""
    runs: list[tuple[int, int, str, str]] = []
    for i, ((_, pdf_style), (_, web_style)) in enumerate(zip(pdf_sig, web_sig, strict=True)):
        if pdf_style == web_style:
            continue
        joins = runs and runs[-1][2:] == (pdf_style, web_style)
        if joins and _only_punctuation(pdf_sig, runs[-1][1], i):
            runs[-1] = (runs[-1][0], i + 1, pdf_style, web_style)
        else:
            runs.append((i, i + 1, pdf_style, web_style))
    return runs


def _style_edit(pdf: str, web: str, run: tuple[int, int, str, str]) -> dict:
    start, end, pdf_style, web_style = run
    return {
        "pdf": _sides(pdf, *_text_span(_positions(pdf), pdf, start, end)),
        "web": _sides(web, *_text_span(_positions(web), web, start, end)),
        "pdf_style": _STYLE_NAMES[pdf_style],
        "web_style": _STYLE_NAMES[web_style],
    }


def _emphasis_reason(pdf: StyledText, web: StyledText, runs: list) -> dict:
    edits = [_style_edit(pdf.text, web.text, run) for run in runs]
    return {"kind": "emphasis", "edit_count": len(edits), "edits": edits[:MAX_EDITS]}


def _chars(signature: list) -> str:
    return "".join(char for char, _ in signature)


def _empty_side(pdf_chars: str, web_chars: str) -> dict | None:
    if not pdf_chars and web_chars:
        return {"kind": "pdf_empty"}
    if pdf_chars and not web_chars:
        return {"kind": "web_empty"}
    return None


def describe_difference(pdf: StyledText, web: StyledText) -> dict | None:
    """None when the two match (text and bold/italic)."""
    pdf_sig, web_sig = pdf.signature(), web.signature()
    signatures = (_chars(pdf_sig), _chars(web_sig))
    empty = _empty_side(*signatures)
    if empty is not None:
        return empty
    if signatures[0] != signatures[1]:
        return _text_reason(pdf.text, web.text, signatures)
    runs = _style_runs(pdf_sig, web_sig)
    return _emphasis_reason(pdf, web, runs) if runs else None
