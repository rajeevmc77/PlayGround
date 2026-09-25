#!/usr/bin/env python3
"""Compares output/bcbc_pdf.json against output/bcbc_web.json by unified_number:
per document level, how many keys are in both files, only the PDF, or only
the web. With --diff, also lists matched keys whose text differs.

Usage:
    python3 src/compare_unified.py
    python3 src/compare_unified.py --diff --limit 20
"""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "output" / "bcbc_pdf.json")
DEFAULT_WEB = str(PROJECT_ROOT / "output" / "bcbc_web.json")

# PDF node types are TitleCase; web nav types are the site's raw lowercase names.
# Both spellings map to one normalized level name.
LEVEL_OF = {
    "Volume": "volume",
    "volume": "volume",
    "Division": "division",
    "division": "division",
    "Part": "part",
    "part": "part",
    "Section": "section",
    "section": "section",
    "Subsection": "subsection",
    "subsection": "subsection",
    "Article": "article",
    "article": "article",
    "Sentence": "sentence",
    "Clause": "clause",
    "Subclause": "subclause",
    "NotesContainer": "notes",
    "part_appendix": "notes",
    "Note": "note",
    "Appendix": "appendix",
    "division_appendix": "appendix",
    "Table": "table",
    "Row": "row",
    "Cell": "cell",
}
LEVELS = [*dict.fromkeys(LEVEL_OF.values()), "image"]
_REF_RE = re.compile(r"\[REF:[^\]]*:([^\]:]*)\]")


@dataclass(frozen=True)
class LevelCount:
    level: str
    pdf: int
    web: int
    both: int

    @property
    def pdf_only(self) -> int:
        return self.pdf - self.both

    @property
    def web_only(self) -> int:
        return self.web - self.both


def _walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def _image_keys(images: list[dict]) -> dict[str, dict]:
    return {i["unified_number"]: i for i in images if i.get("unified_number")}


def collect_keys(tree: dict, images: list[dict]) -> dict[str, dict[str, dict]]:
    keys: dict[str, dict[str, dict]] = {level: {} for level in LEVELS}
    for node in _walk(tree):
        level = LEVEL_OF.get(node["type"])
        if level and node.get("unified_number"):
            keys[level][node["unified_number"]] = node
    keys["image"] = _image_keys(images)
    return keys


def level_counts(pdf_keys: dict, web_keys: dict) -> list[LevelCount]:
    return [
        LevelCount(
            level,
            len(pdf_keys[level]),
            len(web_keys[level]),
            len(pdf_keys[level].keys() & web_keys[level].keys()),
        )
        for level in LEVELS
    ]


def comparable_text(node: dict) -> str:
    text = node.get("content") or node.get("title") or ""
    heading = node.get("heading", "")
    if heading and text.startswith(heading):
        stripped = text[len(heading) :].lstrip(" -")
        if stripped:
            text = stripped
    return " ".join(_REF_RE.sub(r"\1", text).lower().split())


def text_mismatches(pdf_nodes: dict, web_nodes: dict) -> list[tuple[str, str, str]]:
    mismatches = []
    for key in sorted(pdf_nodes.keys() & web_nodes.keys()):
        pdf_text, web_text = comparable_text(pdf_nodes[key]), comparable_text(web_nodes[key])
        if pdf_text != web_text:
            mismatches.append((key, pdf_text, web_text))
    return mismatches


def format_report(counts: list[LevelCount]) -> str:
    header = f"{'level':<12}{'pdf':>8}{'web':>8}{'both':>8}{'pdf-only':>10}{'web-only':>10}"
    rows = [
        f"{c.level:<12}{c.pdf:>8}{c.web:>8}{c.both:>8}{c.pdf_only:>10}{c.web_only:>10}"
        for c in counts
    ]
    return "\n".join([header, *rows])


def _keys_for(path: str) -> dict:
    payload = json.loads(Path(path).read_text())
    tree = payload.get("volume") or payload.get("tree")
    return collect_keys(tree, payload.get("images", []))


def _print_diffs(pdf_keys: dict, web_keys: dict, limit: int) -> None:
    for level in LEVELS[:-1]:  # images carry no comparable text
        mismatches = text_mismatches(pdf_keys[level], web_keys[level])
        if not mismatches:
            continue
        print(f"\n{level}: {len(mismatches)} text mismatches")
        for key, pdf_text, web_text in mismatches[:limit]:
            print(f"  {key}\n    pdf: {pdf_text[:120]}\n    web: {web_text[:120]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", default=DEFAULT_PDF)
    parser.add_argument("--web", default=DEFAULT_WEB)
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    pdf_keys, web_keys = _keys_for(args.pdf), _keys_for(args.web)
    print(format_report(level_counts(pdf_keys, web_keys)))
    if args.diff:
        _print_diffs(pdf_keys, web_keys, args.limit)


if __name__ == "__main__":
    main()
