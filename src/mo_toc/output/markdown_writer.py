from collections import Counter
from pathlib import Path

from mo_toc.domain.models import Caption, Node


def _iter_nodes(node: Node):
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _summary_section(volume: Node) -> list[str]:
    counts = Counter(n.type for n in _iter_nodes(volume))
    lines = ["## Summary", "", "| Level | Count |", "|---|---|"]
    for level in (
        "Division",
        "Part",
        "NotesContainer",
        "Note",
        "Section",
        "Subsection",
        "Article",
        "Appendix",
        "AppendixPart",
        "AppendixSection",
        "AppendixArticle",
        "Sentence",
        "Clause",
        "Subclause",
        "FrontMatter",
        "BackMatter",
    ):
        lines.append(f"| {level} | {counts.get(level, 0)} |")
    return lines + [""]


def _hierarchy_section(volume: Node) -> list[str]:
    skip = {"Sentence", "Clause", "Subclause"}
    lines = [
        "## Document Level Index",
        "",
        "| Level | Citation | Title | Page | End Page |",
        "|---|---|---|---|---|",
    ]

    def walk(node: Node, depth: int):
        if node.type not in skip:
            indent = "&nbsp;&nbsp;" * depth
            title = node.title.replace("|", "\\|")
            lines.append(
                f"| {indent}{node.type} | {node.citation} | {title} | "
                f"{node.page} | {node.end_page} |"
            )
        for child in node.children:
            if child.type not in skip:
                walk(child, depth + 1)

    walk(volume, 0)
    return lines + [""]


def _caption_section(captions: list[Caption], kind: str) -> list[str]:
    items = [c for c in captions if c.kind == kind]
    lines = [
        f"## {kind} Index",
        "",
        "| # | Identifier | Title | Owner | Page |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(sorted(items, key=lambda c: c.page), start=1):
        title = c.title.replace("|", "\\|")
        lines.append(f"| {i} | {c.identifier} | {title} | {c.owner_citation} | {c.page} |")
    return lines + [""]


def write_markdown(volume: Node, captions: list[Caption], out_path: str) -> None:
    lines = ["# MO Package BCBC MRK signed.pdf — Structural Index", ""]
    lines += _summary_section(volume)
    lines += _hierarchy_section(volume)
    lines += _caption_section(captions, "Table")
    lines += _caption_section(captions, "Figure")
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
