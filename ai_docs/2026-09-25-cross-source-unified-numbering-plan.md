# Cross-source Unified Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every node (and image) in `output/bcbc_pdf.json` and `output/bcbc_web.json` a `unified_number` that is the same string in both files for the same piece of the code, add a literal `heading` field, title/nest "Notes to Part N" the website's way, and ship a `compare_unified.py` report.

**Architecture:** `src/shared/numbering.py` swaps its positional algorithm for a rule-driven one: each pipeline hands it a `{node type: Rule}` table plus a set of "scope" types, and it builds keys from official identifiers (only falling back to sibling position for things with no official number). The PDF pipeline gains a post-build step that nests each `NotesContainer` under its Part; the web pipeline gains a Note extractor for the site's `application_note` entries. Both number their image lists from the citation → scope-key map the numbering pass returns.

**Tech Stack:** Python 3.11, pytest, ruff, radon, vulture; existing PyMuPDF (PDF) and httpx (web) pipelines — no new dependencies.

**Spec:** `ai_docs/2026-09-25-cross-source-unified-numbering-design.md`

## Global Constraints

- Functions ≤ 20 executable lines, cyclomatic complexity ≤ 6, nesting ≤ 2 levels; guard clauses over nested if/else (CLAUDE.md).
- Domain/numbering logic stays free of HTTP, file I/O and PDF-library specifics; `shared/` must not import `mo_toc` or `web_toc`.
- TDD: failing test → minimum code → refactor. Existing tests whose **expected numbers** encode the old positional scheme (`test_numbering.py`, `test_mo_toc_numbering_config.py`, `test_web_toc_numbering_config.py`, `test_mo_toc_numbering_integration.py`, the `unified_number` asserts in `test_build_web_toc.py`, the wiring test in `test_build_mo_toc.py`) are **rewritten to the approved new scheme**, not deleted or weakened — each rewrite keeps the same behaviour it covered (numbering is assigned, nested, per-type) under the new keys.
- Volume never appears in a descendant's key. Keys that restart the chain (Volume, Division, division appendix, front/back matter) are never `~n`-suffixed.
- Web `title` stays the site's verbatim nav title (the web tab's `web_toc_view.mjs` depends on it). Only the PDF's Notes-to-Part title changes (to `Notes to Part N`).
- Every "Notes to Part N" lives under Part N of the same division as that Part's last child; no match → `ValueError`.
- Definition of done: `ruff check --fix . && ruff format .`, `radon cc -s -n B .` (nothing C or worse), `vulture .`, `pytest --cov=.` all green.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run everything from the worktree root; the source PDF lives only in the main checkout: `/Users/rajeev/Projects/PlayGround/data/MO Package BCBC MRK signed.pdf`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/shared/numbering.py` | rewrite | `Rule`, `normalize_identifier`, `assign_unified_numbers` (rule-driven, returns citation → scope key), `number_images` |
| `src/mo_toc/domain/models.py` | modify | `Node.heading`, `ImageAsset.unified_number` |
| `src/mo_toc/parsing/tree_builder.py` | modify | record `heading`; Notes-to-Part title = `Notes to Part N` |
| `src/mo_toc/parsing/notes_nesting.py` | create | `nest_notes_under_parts(volume)` |
| `src/mo_toc/parsing/numbering_config.py` | rewrite | `MO_TOC_RULES`, `MO_TOC_SCOPE_TYPES` |
| `src/mo_toc/output/json_writer.py` | modify | drop empty `heading` from JSON |
| `src/build_mo_toc.py` | modify | nest notes in `build_document`; new numbering + image numbering in `run` |
| `src/web_toc/domain/models.py` | modify | `WebNode.heading`, `WebImage.unified_number` |
| `src/web_toc/parsing/tree_builder.py` | modify | `heading_for(title)`; set `heading` on nav nodes |
| `src/web_toc/parsing/note_extractor.py` | create | `extract_notes(content, citations, fallback)` → Note WebNodes |
| `src/web_toc/parsing/numbering_config.py` | rewrite | `WEB_TOC_RULES`, `WEB_TOC_SCOPE_TYPES` |
| `src/build_web_toc.py` | modify | attach notes before tables/images; new numbering + image numbering |
| `src/compare_unified.py` | create | per-level key report + `--diff` text mismatches |
| `CLAUDE.md` | modify | mention `compare_unified.py` and add it to the checklist scope |
| tests | see each task | |

---

### Task 1: Rule-driven shared numbering

**Files:**
- Rewrite: `src/shared/numbering.py`
- Rewrite: `tests/test_numbering.py` (old positional tests replaced by the new scheme's tests)

**Interfaces:**
- Produces:
  - `Rule(kind: str, prefix: str = "", scoped: bool = False, fallback: str = "")` (frozen dataclass). Kinds: `fixed`, `root`, `absolute`, `child`, `suffix`, `literal`, `ordinal`.
  - `normalize_identifier(identifier: str) -> str`
  - `assign_unified_numbers(nodes: list, rules: dict[str, Rule], scope_types: frozenset[str] = frozenset()) -> dict[str, str]` — sets `.unified_number` on every node; returns `{citation: key of nearest enclosing scope node (self included), or the node's own key if none}`.
  - `number_images(images: list, scope_by_citation: dict[str, str], skip: Callable[[object], bool] | None = None) -> None` — sets `.unified_number = f"{scope}.Fig{n}"`.

- [ ] **Step 1: Replace `tests/test_numbering.py` with the new behaviour's tests**

```python
from dataclasses import dataclass, field

import pytest

from shared.numbering import Rule, assign_unified_numbers, normalize_identifier, number_images


@dataclass
class _StubNode:
    type: str
    identifier: str = ""
    citation: str = ""
    children: list["_StubNode"] = field(default_factory=list)
    unified_number: str = ""


@dataclass
class _StubImage:
    owner_citation: str
    decorative: bool = False
    unified_number: str = ""


RULES = {
    "Volume": Rule("root", "V"),
    "Division": Rule("root", fallback="FM"),
    "Appendix": Rule("root", "App"),
    "FrontMatter": Rule("fixed", "FM"),
    "Part": Rule("absolute"),
    "Article": Rule("absolute"),
    "Note": Rule("absolute"),
    "Sentence": Rule("child"),
    "Clause": Rule("suffix"),
    "Notes": Rule("literal", "Notes"),
    "Table": Rule("ordinal", "Tbl", scoped=True),
    "Row": Rule("ordinal", "Row"),
}
SCOPES = frozenset({"Article", "Note"})


def test_normalize_identifier_strips_trailing_dot_and_collapses_spaces():
    assert normalize_identifier("9.10.18.2.") == "9.10.18.2"
    assert normalize_identifier(" A-3.1.4.1.(1)  and (2) ") == "A-3.1.4.1.(1) and (2)"
    assert normalize_identifier("") == ""


def test_official_numbers_build_the_key_and_volume_is_left_out():
    clause = _StubNode("Clause", "(a)", "c")
    sentence = _StubNode("Sentence", "(2)", "s", [clause])
    article = _StubNode("Article", "9.10.18.2.", "a", [sentence])
    part = _StubNode("Part", "9", "p", [article])
    division = _StubNode("Division", "B", "d", [part])
    volume = _StubNode("Volume", "2", "v", [division])

    assign_unified_numbers([volume], RULES, SCOPES)

    assert volume.unified_number == "V2"
    assert division.unified_number == "B"
    assert part.unified_number == "B.9"
    assert article.unified_number == "B.9.10.18.2"
    assert sentence.unified_number == "B.9.10.18.2.(2)"
    assert clause.unified_number == "B.9.10.18.2.(2)(a)"


def test_missing_sibling_does_not_shift_later_keys():
    part10 = _StubNode("Part", "10", "p10")
    division = _StubNode("Division", "B", "d", [part10])  # Part 9 absent

    assign_unified_numbers([division], RULES)

    assert part10.unified_number == "B.10"


def test_literal_appends_fixed_segment_to_parent():
    notes = _StubNode("Notes", "1", "n")
    part = _StubNode("Part", "1", "p", [notes])
    division = _StubNode("Division", "A", "d", [part])

    assign_unified_numbers([division], RULES)

    assert notes.unified_number == "A.1.Notes"


def test_note_key_is_division_plus_official_note_number():
    note = _StubNode("Note", "A-1.1.1.1.(3)", "note")
    notes = _StubNode("Notes", "1", "n", [note])
    part = _StubNode("Part", "1", "p", [notes])
    division = _StubNode("Division", "A", "d", [part])

    assign_unified_numbers([division], RULES, SCOPES)

    assert note.unified_number == "A.A-1.1.1.1.(3)"


def test_scoped_table_ordinal_counts_within_owning_article_not_tree_parent():
    table_in_sentence = _StubNode("Table", "x", "t1")
    sentence = _StubNode("Sentence", "(1)", "s", [table_in_sentence])
    table_in_article = _StubNode("Table", "y", "t2")
    article = _StubNode("Article", "1.1.1.1", "a", [sentence, table_in_article])
    division = _StubNode("Division", "A", "d", [article])

    assign_unified_numbers([division], RULES, SCOPES)

    assert table_in_sentence.unified_number == "A.1.1.1.1.Tbl1"
    assert table_in_article.unified_number == "A.1.1.1.1.Tbl2"


def test_unscoped_ordinal_counts_under_parent():
    rows = [_StubNode("Row", "", f"r{i}") for i in range(2)]
    table = _StubNode("Table", "t", "t", rows)
    article = _StubNode("Article", "1.1.1.1", "a", [table])
    division = _StubNode("Division", "A", "d", [article])

    assign_unified_numbers([division], RULES, SCOPES)

    assert [r.unified_number for r in rows] == ["A.1.1.1.1.Tbl1.Row1", "A.1.1.1.1.Tbl1.Row2"]


def test_empty_identifier_uses_fallback_then_ordinal():
    article = _StubNode("Article", "", "a")
    preface = _StubNode("Division", "", "pre", [article])

    assign_unified_numbers([preface], RULES)

    assert preface.unified_number == "FM"
    assert article.unified_number == "FM.Article1"


def test_unmapped_type_is_an_ordinal_named_after_its_type():
    mystery = _StubNode("mystery", "", "m")
    division = _StubNode("Division", "A", "d", [mystery])

    assign_unified_numbers([division], RULES)

    assert mystery.unified_number == "A.mystery1"


def test_duplicate_key_gets_tilde_suffix():
    first = _StubNode("Part", "1", "p1")
    second = _StubNode("Part", "1", "p2")
    division = _StubNode("Division", "A", "d", [first, second])

    assign_unified_numbers([division], RULES)

    assert first.unified_number == "A.1"
    assert second.unified_number == "A.1~2"


def test_division_split_across_volumes_keeps_one_key():
    part1 = _StubNode("Part", "1", "p1")
    part9 = _StubNode("Part", "9", "p9")
    vol1 = _StubNode("Volume", "1", "v1", [_StubNode("Division", "B", "d1", [part1])])
    vol2 = _StubNode("Volume", "2", "v2", [_StubNode("Division", "B", "d2", [part9])])

    assign_unified_numbers([vol1, vol2], RULES)

    assert vol2.children[0].unified_number == "B"
    assert part9.unified_number == "B.9"


def test_fixed_and_root_prefix_rules():
    front = _StubNode("FrontMatter", "FrontMatter", "fm")
    appendix = _StubNode("Appendix", "D", "app")

    assign_unified_numbers([front, appendix], RULES)

    assert front.unified_number == "FM"
    assert appendix.unified_number == "AppD"


def test_unknown_rule_kind_raises():
    with pytest.raises(KeyError):
        assign_unified_numbers([_StubNode("X", "1", "x")], {"X": Rule("bogus")})


def test_returns_scope_key_per_citation():
    clause = _StubNode("Clause", "(a)", "clause-cit")
    sentence = _StubNode("Sentence", "(1)", "sent-cit", [clause])
    article = _StubNode("Article", "1.1.1.1", "art-cit", [sentence])
    front = _StubNode("FrontMatter", "", "fm-cit")
    division = _StubNode("Division", "A", "div-cit", [article])

    scope = assign_unified_numbers([front, division], RULES, SCOPES)

    assert scope["clause-cit"] == "A.1.1.1.1"
    assert scope["art-cit"] == "A.1.1.1.1"
    assert scope["fm-cit"] == "FM"


def test_empty_node_list_returns_empty_map():
    assert assign_unified_numbers([], RULES) == {}


def test_number_images_counts_per_scope_and_skips():
    images = [
        _StubImage("clause-cit"),
        _StubImage("clause-cit", decorative=True),
        _StubImage("art-cit"),
        _StubImage("unknown-cit"),
    ]
    scope = {"clause-cit": "A.1.1.1.1", "art-cit": "A.1.1.1.1"}

    number_images(images, scope, skip=lambda image: image.decorative)

    assert [i.unified_number for i in images] == ["A.1.1.1.1.Fig1", "", "A.1.1.1.1.Fig2", ""]


def test_number_images_without_skip_numbers_everything_resolvable():
    images = [_StubImage("a"), _StubImage("a")]

    number_images(images, {"a": "B.9.1.1.1"})

    assert [i.unified_number for i in images] == ["B.9.1.1.1.Fig1", "B.9.1.1.1.Fig2"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_numbering.py -q`
Expected: FAIL — `ImportError: cannot import name 'Rule'`.

- [ ] **Step 3: Rewrite `src/shared/numbering.py`**

```python
"""Assigns every node a cross-source unified_number built from the building
code's own numbering, so the same clause/table/note gets the same key in
bcbc_pdf.json and bcbc_web.json (design:
ai_docs/2026-09-25-cross-source-unified-numbering-design.md).

Each pipeline supplies a {node type: Rule} table. Sibling position is used only
by the "ordinal" rule, for things with no official number. Duck-types on any
object exposing `.type`, `.identifier`, `.citation`, `.children` and a settable
`.unified_number` - no dependency on either domain model.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

# Kinds whose key restarts the chain: nothing above them (e.g. the volume)
# leaks into descendants' keys, and they are never ~n-suffixed - the web
# splits Division B across two volumes and both must stay "B".
_RESTART_KINDS = frozenset({"fixed", "root"})
_IDENTIFIER_KINDS = frozenset({"root", "absolute", "child", "suffix"})


@dataclass(frozen=True)
class Rule:
    """kind:
    fixed    -> `prefix` verbatim ("V1", "FM")
    root     -> prefix + identifier ("B", "AppD", "V2")
    absolute -> nearest restart key + "." + identifier ("B.9.10.18.2")
    child    -> parent key + "." + identifier ("B.9.10.18.2.(2)")
    suffix   -> parent key + identifier, no dot ("B.9.10.18.2.(2)(a)")
    literal  -> parent key + "." + prefix ("B.9.Notes")
    ordinal  -> base + "." + prefix + n, counting same-type nodes under base;
                base is the enclosing scope node when `scoped`, else the parent.
    `fallback` (identifier kinds only) is a fixed key used when the
    identifier is empty (the web's unnumbered "Preface" division -> "FM").
    """

    kind: str
    prefix: str = ""
    scoped: bool = False
    fallback: str = ""


@dataclass(frozen=True)
class _Context:
    parent_key: str = ""
    root_key: str = ""
    scope_key: str = ""


@dataclass
class _Walk:
    rules: dict[str, Rule]
    scope_types: frozenset[str]
    counters: dict[tuple[str, str], int] = field(default_factory=dict)
    seen: dict[str, int] = field(default_factory=dict)
    scope_by_citation: dict[str, str] = field(default_factory=dict)


def normalize_identifier(identifier: str) -> str:
    return " ".join(identifier.split()).rstrip(".")


def _join(base: str, segment: str) -> str:
    return f"{base}.{segment}" if base else segment


_BUILDERS: dict[str, Callable[[str, Rule, _Context], str]] = {
    "fixed": lambda ident, rule, ctx: rule.prefix,
    "root": lambda ident, rule, ctx: f"{rule.prefix}{ident}",
    "absolute": lambda ident, rule, ctx: _join(ctx.root_key, ident),
    "child": lambda ident, rule, ctx: _join(ctx.parent_key, ident),
    "suffix": lambda ident, rule, ctx: f"{ctx.parent_key}{ident}",
    "literal": lambda ident, rule, ctx: _join(ctx.parent_key, rule.prefix),
}


def _rule_for(node, walk: _Walk) -> Rule:
    rule = walk.rules.get(node.type, Rule("ordinal", node.type))
    if rule.kind not in _IDENTIFIER_KINDS or normalize_identifier(node.identifier):
        return rule
    if rule.fallback:
        return Rule("fixed", rule.fallback)
    return Rule("ordinal", node.type)


def _ordinal(node, rule: Rule, ctx: _Context, walk: _Walk) -> str:
    base = ctx.scope_key if rule.scoped else ctx.parent_key
    counter = (base, node.type)
    walk.counters[counter] = walk.counters.get(counter, 0) + 1
    return _join(base, f"{rule.prefix}{walk.counters[counter]}")


def _key_for(node, rule: Rule, ctx: _Context, walk: _Walk) -> str:
    if rule.kind == "ordinal":
        return _ordinal(node, rule, ctx, walk)
    return _BUILDERS[rule.kind](normalize_identifier(node.identifier), rule, ctx)


def _unique(key: str, rule: Rule, walk: _Walk) -> str:
    if rule.kind in _RESTART_KINDS:
        return key
    count = walk.seen.get(key, 0) + 1
    walk.seen[key] = count
    return key if count == 1 else f"{key}~{count}"


def _child_context(node, key: str, rule: Rule, ctx: _Context, walk: _Walk) -> _Context:
    restarts = rule.kind in _RESTART_KINDS
    root_key = key if restarts else ctx.root_key
    scope_key = key if restarts or node.type in walk.scope_types else ctx.scope_key
    return _Context(parent_key=key, root_key=root_key, scope_key=scope_key)


def _number(nodes: list, ctx: _Context, walk: _Walk) -> None:
    for node in nodes:
        rule = _rule_for(node, walk)
        node.unified_number = _unique(_key_for(node, rule, ctx, walk), rule, walk)
        child_ctx = _child_context(node, node.unified_number, rule, ctx, walk)
        walk.scope_by_citation[node.citation] = child_ctx.scope_key or node.unified_number
        _number(node.children, child_ctx, walk)


def assign_unified_numbers(
    nodes: list, rules: dict[str, Rule], scope_types: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Numbers `nodes` and all descendants in place. Returns citation -> key of
    that node's nearest enclosing scope node (itself included), which
    number_images uses to key an image by its owner."""
    walk = _Walk(rules=rules, scope_types=scope_types)
    _number(nodes, _Context(), walk)
    return walk.scope_by_citation


def number_images(
    images: list,
    scope_by_citation: dict[str, str],
    skip: Callable[[object], bool] | None = None,
) -> None:
    counters: dict[str, int] = {}
    for image in images:
        base = scope_by_citation.get(image.owner_citation)
        if base is None or (skip is not None and skip(image)):
            continue
        counters[base] = counters.get(base, 0) + 1
        image.unified_number = f"{base}.Fig{counters[base]}"
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_numbering.py -q`
Expected: all pass. (`tests/test_mo_toc_numbering_*`, `test_web_toc_numbering_config.py`, `test_build_*` now fail on import/old expectations — fixed in Tasks 4 and 7; do not touch them here.)

- [ ] **Step 5: Commit**

```bash
git add src/shared/numbering.py tests/test_numbering.py
git commit -m "feat(shared): rule-driven cross-source unified numbering

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: PDF headings and the "Notes to Part N" title

**Files:**
- Modify: `src/mo_toc/domain/models.py` (add `heading: str = ""` as the **last** field of `Node`; add `unified_number: str = ""` as the last field of `ImageAsset`)
- Modify: `src/mo_toc/parsing/tree_builder.py` (`_open_node`, `_open_note`, new `_heading_text`, `_heading_title`)
- Modify: `src/mo_toc/output/json_writer.py` (`_prune_node`)
- Test: `tests/test_tree_builder.py`, `tests/test_domain_models.py`, `tests/test_json_writer.py`

**Interfaces:**
- Produces: `Node.heading`; `ImageAsset.unified_number`; a `NotesContainer` node's `title == heading == "Notes to Part N"`; a `Note`'s `heading == identifier`.

- [ ] **Step 1: Write failing tests**

In `tests/test_domain_models.py` add:

```python
def test_node_heading_defaults_to_empty_string():
    node = Node(type="Part", identifier="1", citation="A-1", title="", page=1, end_page=1,
                bbox=BBox(0, 0, 0, 0))
    assert node.heading == ""


def test_image_asset_unified_number_defaults_to_empty_string():
    image = ImageAsset(page=1, bbox=BBox(0, 0, 1, 1), width=1, height=1, phash=None,
                       image_path="images/img_0.png")
    assert image.unified_number == ""
```

(Add `ImageAsset` to that file's import from `mo_toc.domain.models` if not already imported.)

In `tests/test_tree_builder.py`, reuse that file's existing line-building helpers (the ones the current NotesContainer test at ~line 97 uses to fabricate `PageLine`s with an Arial-Black font) and add:

```python
def test_heading_records_literal_heading_words():
    volume, _ = build_tree_from_lines(
        [[
            _line("Division A", font="Arial-Black"),
            _line("Part 1", font="Arial-Black"),
            _line("Compliance", font="Arial-Black"),
            _line("Section 1.1. General", font="Arial-Black"),
            _line("1.1.1.1. Application of this Code", font="Arial-Black"),
        ]],
        1,
    )
    division = volume.children[1]
    part = division.children[0]
    section = part.children[0]
    article = section.children[0]
    assert division.heading == "Division A"
    assert (part.heading, part.title) == ("Part 1", "Compliance")
    assert (section.heading, section.title) == ("Section 1.1.", "General")
    assert (article.heading, article.title) == ("1.1.1.1.", "Application of this Code")


def test_notes_container_title_is_notes_to_part_n():
    volume, _ = build_tree_from_lines(
        [[
            _line("Division A", font="Arial-Black"),
            _line("Part 1", font="Arial-Black"),
            _line("Compliance", font="Arial-Black"),
            _line("Notes to Part 1", font="Arial-Black"),
            _line("Compliance", font="Arial-Black"),
            _line("A-1.1.1.1.(3) Factory-Constructed Buildings.", font="Arial"),
        ]],
        1,
    )
    notes = volume.children[1].children[1]
    assert notes.type == "NotesContainer"
    assert notes.title == "Notes to Part 1"
    assert notes.heading == "Notes to Part 1"
    assert notes.children[0].heading == "A-1.1.1.1.(3)"
```

If the existing helper is named differently or takes different arguments, adapt the calls to it — don't add a second helper. Check the existing NotesContainer test for the exact font strings and Note-line font it uses and mirror them.

In `tests/test_json_writer.py` add:

```python
def test_empty_heading_is_pruned_but_real_heading_kept(tmp_path):
    sentence = Node(type="Sentence", identifier="(1)", citation="s", title="", page=1,
                    end_page=1, bbox=BBox(0, 0, 0, 0))
    part = Node(type="Part", identifier="1", citation="A-1", title="Compliance", page=1,
                end_page=1, bbox=BBox(0, 0, 0, 0), children=[sentence], heading="Part 1")
    out = tmp_path / "out.json"

    write_json(part, [], [], str(out))

    payload = json.loads(out.read_text())["volume"]
    assert payload["heading"] == "Part 1"
    assert "heading" not in payload["children"][0]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_domain_models.py tests/test_tree_builder.py tests/test_json_writer.py -q`
Expected: FAIL — `AttributeError`/`TypeError` on `heading`, and notes title `"Compliance"`.

- [ ] **Step 3: Implement**

`src/mo_toc/domain/models.py`: add `heading: str = ""` after `content` in `Node`; add `unified_number: str = ""` after `decorative` in `ImageAsset`.

`src/mo_toc/parsing/tree_builder.py` — add above `_open_node`:

```python
def _heading_text(match, title: str) -> str:
    """The literal heading words - "Part 1", "Section 9.10.", "Notes to Part 1" -
    without any title the same trigger line also carried."""
    if not title or match.lastindex is None:
        return match.group(0).strip()
    return match.string[: match.start(match.lastindex)].strip()


def _heading_title(
    ntype: str, lines: list[PageLine], next_idx: int, title: str, heading: str
) -> tuple[str, int]:
    if ntype == "BackMatter":
        return title, next_idx
    title, next_idx = _consume_heading_title(lines, next_idx, title)
    if ntype == "NotesContainer":
        # The website's own title; the folded-in Part name ("Compliance") is
        # dropped - the parent Part already carries it.
        return heading, next_idx
    return title, next_idx
```

Replace `_open_node` with:

```python
def _open_node(
    ntype: str, match, page_index: int, lines: list[PageLine], idx: int, state: _BuildState
) -> int:
    identifier, title, citation = _citation_for(ntype, match, state.division)
    heading = _heading_text(match, title)
    if ntype == "Division":
        state.division = identifier
    title, next_idx = _heading_title(ntype, lines, idx + 1, title, heading)

    rank = RANK[ntype]
    parent = _close_stack_to_rank(state, rank)
    node = Node(
        type=ntype,
        identifier=identifier,
        citation=citation,
        title=title,
        page=page_index + 1,
        end_page=page_index + 1,
        bbox=BBox(*lines[idx].bbox),
        heading=heading,
    )
    parent.children.append(node)
    state.stack.append((rank, node))
    _update_state_after_open(ntype, node, state)
    return next_idx
```

In `_open_note`, add `heading=identifier,` to the `Node(...)` call.

`src/mo_toc/output/json_writer.py` — in `_prune_node`, before the children line:

```python
    if not node_dict.get("heading"):
        node_dict.pop("heading", None)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_domain_models.py tests/test_tree_builder.py tests/test_json_writer.py tests/test_heading_rules.py -q`
Expected: PASS. If an existing test compares a whole JSON dict/Node and now sees `heading`, update that expected value to include the new field (it's a new field, not a behaviour change).

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/domain/models.py src/mo_toc/parsing/tree_builder.py src/mo_toc/output/json_writer.py tests/
git commit -m "feat(mo_toc): record literal headings; title Notes-to-Part nodes 'Notes to Part N'

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Nest each "Notes to Part N" under its Part (PDF)

**Files:**
- Create: `src/mo_toc/parsing/notes_nesting.py`
- Modify: `src/build_mo_toc.py` (`build_document`)
- Test: `tests/test_notes_nesting.py` (new), `tests/test_build_mo_toc.py`

**Interfaces:**
- Consumes: `Node` from `mo_toc.domain.models`.
- Produces: `nest_notes_under_parts(volume: Node) -> None` — raises `ValueError` for a container with no matching Part.

- [ ] **Step 1: Write failing tests** — `tests/test_notes_nesting.py`:

```python
import pytest

from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.notes_nesting import nest_notes_under_parts


def _node(node_type, identifier, children=None, page=1, end_page=1):
    return Node(type=node_type, identifier=identifier, citation=f"{node_type}-{identifier}",
                title="", page=page, end_page=end_page, bbox=BBox(0, 0, 0, 0),
                children=children or [])


def _volume(*division_children, division="A"):
    return _node("Volume", "Volume", [_node("Division", division, list(division_children))])


def test_notes_container_moves_to_end_of_matching_part():
    section = _node("Section", "1.1.")
    part1 = _node("Part", "1", [section], page=1, end_page=9)
    notes1 = _node("NotesContainer", "1", page=10, end_page=12)
    part2 = _node("Part", "2", page=13, end_page=20)
    volume = _volume(part1, notes1, part2)

    nest_notes_under_parts(volume)

    division = volume.children[0]
    assert division.children == [part1, part2]
    assert part1.children == [section, notes1]
    assert part1.end_page == 12


def test_part_without_notes_is_untouched():
    part2 = _node("Part", "2")
    volume = _volume(part2)

    nest_notes_under_parts(volume)

    assert part2.children == []


def test_notes_container_without_matching_part_raises():
    volume = _volume(_node("Part", "1"), _node("NotesContainer", "7"))

    with pytest.raises(ValueError, match="Part 7"):
        nest_notes_under_parts(volume)


def test_non_division_children_of_volume_are_ignored():
    front = _node("FrontMatter", "FrontMatter")
    volume = _node("Volume", "Volume", [front])

    nest_notes_under_parts(volume)

    assert volume.children == [front]
```

In `tests/test_build_mo_toc.py` add a test that `build_document` calls `nest_notes_under_parts` with the built volume **before** `attach_tables` (patch `build_mo_toc.build_tree_from_lines`, `build_mo_toc.fill_continuation_gaps`, `build_mo_toc.stitch_continuations`, `build_mo_toc.attach_tables`, `build_mo_toc.nest_notes_under_parts`; attach them to one `MagicMock` manager like `test_run_wires_pipeline_in_order` does and assert the call order `["fill_continuation_gaps", "build_tree_from_lines", "nest_notes_under_parts", "stitch_continuations", "attach_tables"]`; make `build_tree_from_lines` return `("VOLUME", [])`).

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_notes_nesting.py tests/test_build_mo_toc.py -q`
Expected: FAIL — `ModuleNotFoundError: mo_toc.parsing.notes_nesting`.

- [ ] **Step 3: Implement** — `src/mo_toc/parsing/notes_nesting.py`:

```python
"""Moves each "Notes to Part N" container from beside the Parts - where the
rank-based tree builder leaves it, since NotesContainer shares Part's rank -
into Part N of the same Division as that Part's last child: the website's
own layout. Runs after build_tree_from_lines, so the builder's own
stack-close logic is untouched."""

from mo_toc.domain.models import Node


def nest_notes_under_parts(volume: Node) -> None:
    for division in volume.children:
        if division.type == "Division":
            _nest_in_division(division)


def _nest_in_division(division: Node) -> None:
    parts = {child.identifier: child for child in division.children if child.type == "Part"}
    kept = []
    for child in division.children:
        if child.type != "NotesContainer":
            kept.append(child)
            continue
        _move_into_part(child, parts, division)
    division.children = kept


def _move_into_part(notes: Node, parts: dict[str, Node], division: Node) -> None:
    part = parts.get(notes.identifier)
    if part is None:
        raise ValueError(
            f"{notes.citation}: no Part {notes.identifier} in Division {division.identifier}"
        )
    part.children.append(notes)
    part.end_page = max(part.end_page, notes.end_page)
```

`src/build_mo_toc.py`: import `from mo_toc.parsing.notes_nesting import nest_notes_under_parts` and in `build_document` insert `nest_notes_under_parts(volume)` immediately after the `build_tree_from_lines(...)` assignment.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_notes_nesting.py tests/test_build_mo_toc.py tests/test_image_matcher.py tests/test_table_extractor.py -q`
Expected: new tests PASS. `test_run_wires_pipeline_in_order` may still fail — that's Task 4.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/notes_nesting.py src/build_mo_toc.py tests/test_notes_nesting.py tests/test_build_mo_toc.py
git commit -m "feat(mo_toc): nest each Notes to Part N under its Part

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: PDF numbering rules, image numbers, pipeline wiring

**Files:**
- Rewrite: `src/mo_toc/parsing/numbering_config.py`
- Modify: `src/build_mo_toc.py` (`run`)
- Rewrite: `tests/test_mo_toc_numbering_config.py`, `tests/test_mo_toc_numbering_integration.py`
- Modify: `tests/test_build_mo_toc.py::test_run_wires_pipeline_in_order`

**Interfaces:**
- Consumes: `Rule`, `assign_unified_numbers`, `number_images` (Task 1); `nest_notes_under_parts` (Task 3).
- Produces: `MO_TOC_RULES: dict[str, Rule]`, `MO_TOC_SCOPE_TYPES: frozenset[str]`.

- [ ] **Step 1: Write failing tests**

`tests/test_mo_toc_numbering_config.py` (replace contents):

```python
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from shared.numbering import Rule


def test_official_number_levels_are_absolute():
    for level in ("Part", "Section", "Subsection", "Article", "Note",
                  "AppendixPart", "AppendixSection", "AppendixArticle"):
        assert MO_TOC_RULES[level] == Rule("absolute")


def test_chain_restarting_levels():
    assert MO_TOC_RULES["Volume"] == Rule("fixed", "V1")
    assert MO_TOC_RULES["FrontMatter"] == Rule("fixed", "FM")
    assert MO_TOC_RULES["BackMatter"] == Rule("fixed", "BM")
    assert MO_TOC_RULES["Division"] == Rule("root")
    assert MO_TOC_RULES["Appendix"] == Rule("root", "App")


def test_body_and_table_levels():
    assert MO_TOC_RULES["Sentence"] == Rule("child")
    assert MO_TOC_RULES["Clause"] == Rule("suffix")
    assert MO_TOC_RULES["Subclause"] == Rule("suffix")
    assert MO_TOC_RULES["NotesContainer"] == Rule("literal", "Notes")
    assert MO_TOC_RULES["TableGroup"] == Rule("ordinal", "Spec")
    assert MO_TOC_RULES["Table"] == Rule("ordinal", "Tbl", scoped=True)
    assert MO_TOC_RULES["Row"] == Rule("ordinal", "Row")
    assert MO_TOC_RULES["Cell"] == Rule("ordinal", "Col")


def test_appendix_sub_levels_are_not_table_scopes():
    # the web keeps Appendix C/D tables directly under the appendix
    assert {"AppendixPart", "AppendixSection", "AppendixArticle"}.isdisjoint(MO_TOC_SCOPE_TYPES)
    assert {"Article", "Note", "NotesContainer", "TableGroup"} <= MO_TOC_SCOPE_TYPES
```

`tests/test_mo_toc_numbering_integration.py` (replace the test body; keep the `_node` helper):

```python
def test_real_mo_toc_tree_gets_cross_source_keys():
    subclause = _node("Subclause", "(i)", "A-1.1.1.1.(1)(a)(i)")
    clause = _node("Clause", "(a)", "A-1.1.1.1.(1)(a)", children=[subclause])
    table = _node("Table", "1.1.1.1.", "Table:1.1.1.1.")
    sentence = _node("Sentence", "(1)", "A-1.1.1.1.(1)", children=[clause, table])
    article = _node("Article", "1.1.1.1.", "A-1.1.1.1.", children=[sentence])
    subsection = _node("Subsection", "1.1.1.", "A-1.1.1.", children=[article])
    section = _node("Section", "1.1.", "A-1.1.", children=[subsection])
    note = _node("Note", "A-1.1.1.1.(3)", "Note:A-1.1.1.1.(3)")
    notes = _node("NotesContainer", "1", "Notes-A-1", children=[note])
    part = _node("Part", "1", "A-1", children=[section, notes])
    division = _node("Division", "A", "A", children=[part])
    front = _node("FrontMatter", "FrontMatter", "FrontMatter")
    volume = _node("Volume", "Volume", "Volume", children=[front, division])

    scope = assign_unified_numbers([volume], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)

    assert volume.unified_number == "V1"
    assert front.unified_number == "FM"
    assert division.unified_number == "A"
    assert part.unified_number == "A.1"
    assert section.unified_number == "A.1.1"
    assert subsection.unified_number == "A.1.1.1"
    assert article.unified_number == "A.1.1.1.1"
    assert sentence.unified_number == "A.1.1.1.1.(1)"
    assert clause.unified_number == "A.1.1.1.1.(1)(a)"
    assert subclause.unified_number == "A.1.1.1.1.(1)(a)(i)"
    assert table.unified_number == "A.1.1.1.1.Tbl1"
    assert notes.unified_number == "A.1.Notes"
    assert note.unified_number == "A.A-1.1.1.1.(3)"
    assert scope["A-1.1.1.1.(1)(a)(i)"] == "A.1.1.1.1"
```

Update the imports at the top of that file to `from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES`.

`tests/test_build_mo_toc.py::test_run_wires_pipeline_in_order`: add `@patch("build_mo_toc.number_images")` (as the outermost-but-one decorator, so it arrives as a new parameter `mock_number_images` right before `mock_write_json`), set `mock_assign_numbers.return_value = {"SCOPE": "MAP"}`, attach it to the manager as `"number_images"`, and replace the numbering asserts with:

```python
    mock_assign_numbers.assert_called_once_with(["VOLUME"], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)
    mock_number_images.assert_called_once()
    images_arg, scope_arg = mock_number_images.call_args.args
    assert images_arg == ["MATCHED_IMAGE_ASSET"]
    assert scope_arg == {"SCOPE": "MAP"}
    skip = mock_number_images.call_args.kwargs["skip"]
    assert skip(SimpleNamespace(decorative=True)) is True
    assert skip(SimpleNamespace(decorative=False)) is False
```

and the expected order list becomes `["extract_all_pages", "build_document", "assign_unified_numbers", "drop_images_over_tables", "write_images", "match_images", "number_images", "write_json"]`. Update its imports (`MO_TOC_RULES, MO_TOC_SCOPE_TYPES`; `from types import SimpleNamespace`).

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mo_toc_numbering_config.py tests/test_mo_toc_numbering_integration.py tests/test_build_mo_toc.py -q`
Expected: FAIL — `ImportError: cannot import name 'MO_TOC_RULES'`.

- [ ] **Step 3: Implement**

`src/mo_toc/parsing/numbering_config.py` (replace):

```python
"""mo_toc's cross-source numbering rules: which shared.numbering.Rule builds
each Node.type's unified_number (see
ai_docs/2026-09-25-cross-source-unified-numbering-design.md)."""

from shared.numbering import Rule

_ABSOLUTE = Rule("absolute")

MO_TOC_RULES: dict[str, Rule] = {
    # The MO package is one volume; the volume never enters descendants' keys.
    "Volume": Rule("fixed", "V1"),
    "FrontMatter": Rule("fixed", "FM"),
    "BackMatter": Rule("fixed", "BM"),
    "Division": Rule("root"),
    "Appendix": Rule("root", "App"),
    "Part": _ABSOLUTE,
    "Section": _ABSOLUTE,
    "Subsection": _ABSOLUTE,
    "Article": _ABSOLUTE,
    "Note": _ABSOLUTE,
    "AppendixPart": _ABSOLUTE,
    "AppendixSection": _ABSOLUTE,
    "AppendixArticle": _ABSOLUTE,
    "Sentence": Rule("child"),
    "Clause": Rule("suffix"),
    "Subclause": Rule("suffix"),
    "NotesContainer": Rule("literal", "Notes"),
    # The web's "spectables" pages; same ordinal prefix so the two line up.
    "TableGroup": Rule("ordinal", "Spec"),
    "Table": Rule("ordinal", "Tbl", scoped=True),
    "Row": Rule("ordinal", "Row"),
    "Cell": Rule("ordinal", "Col"),
}

# Nodes that own tables/images for ordinal counting. Appendix sub-levels are
# deliberately absent: the web keeps Appendix C/D tables directly under the
# appendix, so the PDF counts them there too (Appendix restarts the chain,
# which already makes it a scope).
MO_TOC_SCOPE_TYPES: frozenset[str] = frozenset(
    {"Part", "Section", "Subsection", "Article", "NotesContainer", "Note", "TableGroup"}
)
```

`src/build_mo_toc.py`: replace the numbering imports with

```python
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from shared.numbering import assign_unified_numbers, number_images
```

add

```python
def _is_decorative(image) -> bool:
    return image.decorative
```

and make `run`:

```python
def run(pdf_path: str, output_dir: str) -> None:
    all_lines, raw_images, table_regions_by_page, all_drawing_rects = extract_all_pages(pdf_path)
    volume, captions, table_regions_by_page = build_document(
        all_lines, table_regions_by_page, all_drawing_rects
    )
    scope_by_citation = assign_unified_numbers([volume], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)
    raw_images = drop_images_over_tables(raw_images, table_regions_by_page)
    images = write_images(raw_images, str(Path(output_dir) / "images"))
    images = match_images(images, captions, volume)
    number_images(images, scope_by_citation, skip=_is_decorative)
    write_json(volume, captions, images, str(Path(output_dir) / "bcbc_pdf.json"))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_mo_toc_numbering_config.py tests/test_mo_toc_numbering_integration.py tests/test_build_mo_toc.py tests/test_serve_mo_toc.py tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/numbering_config.py src/build_mo_toc.py tests/test_mo_toc_numbering_config.py tests/test_mo_toc_numbering_integration.py tests/test_build_mo_toc.py
git commit -m "feat(mo_toc): number the PDF tree and images with cross-source keys

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Web headings

**Files:**
- Modify: `src/web_toc/domain/models.py` (`WebNode.heading: str = ""` last field; `WebImage.unified_number: str = ""` last field)
- Modify: `src/web_toc/parsing/tree_builder.py`
- Test: `tests/test_web_toc_tree_builder.py`, `tests/test_web_toc_domain_models.py`

**Interfaces:**
- Produces: `heading_for(title: str) -> str`; nav `WebNode`s carry `heading`; `title` unchanged.

- [ ] **Step 1: Write failing tests** — in `tests/test_web_toc_tree_builder.py`:

```python
import pytest

from web_toc.parsing.tree_builder import build_tree, heading_for


@pytest.mark.parametrize(
    ("title", "heading"),
    [
        ("Part 1 - Compliance", "Part 1"),
        ("Division A - Compliance, Objectives and Functional Statements", "Division A"),
        ("Volume 2", "Volume 2"),
        ("Notes to Part 1", "Notes to Part 1"),
        ("10.1.1.1 Scope", "10.1.1.1"),
        ("10.1 General", "10.1"),
        ("Preface", ""),
        ("", ""),
    ],
)
def test_heading_for(title, heading):
    assert heading_for(title) == heading


def test_nav_nodes_get_heading_and_keep_verbatim_title():
    root = build_tree({"tree": [{"id": "nbc.divA.part1", "type": "part", "number": "1",
                                  "title": "Part 1 - Compliance", "path": "/x"}]})
    part = root.children[0]
    assert part.heading == "Part 1"
    assert part.title == "Part 1 - Compliance"
```

(Merge the imports with the file's existing ones.) In `tests/test_web_toc_domain_models.py` add default-value tests for `WebNode.heading` and `WebImage.unified_number` (both `""`), mirroring the existing `unified_number` default test there.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_toc_tree_builder.py tests/test_web_toc_domain_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'heading_for'`.

- [ ] **Step 3: Implement**

Models: add the two fields. `src/web_toc/parsing/tree_builder.py`:

```python
_HEADING_RE = re.compile(
    r"^(?P<heading>(?:Volume|Division|Part)\s+\S+|Notes to Part\s+\d+|\d+(?:\.\d+)+)"
)


def heading_for(title: str) -> str:
    """The literal heading words at the front of a nav title ("Part 1",
    "10.1.1.1", "Notes to Part 1"). The title itself stays verbatim - the
    web tab's sidebar labels are built from it."""
    match = _HEADING_RE.match(title.strip())
    return match.group("heading") if match else ""
```

and in `_convert` add `heading=heading_for(raw.get("title", "")),`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_web_toc_tree_builder.py tests/test_web_toc_domain_models.py tests/test_web_toc_json_writer.py -q`
Expected: PASS (update any whole-dict expectation in `test_web_toc_json_writer.py` to include the new `heading`/`unified_number` fields).

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/domain/models.py src/web_toc/parsing/tree_builder.py tests/
git commit -m "feat(web_toc): record literal heading on nav nodes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Web Notes from `application_note`

**Files:**
- Create: `src/web_toc/parsing/note_extractor.py`
- Modify: `src/build_web_toc.py` (`run` split into helpers; notes attached and added to `citations` before tables/images/body are resolved)
- Test: `tests/test_web_toc_note_extractor.py` (new), `tests/test_build_web_toc.py`

**Interfaces:**
- Consumes: `resolve_owner`, `attach_owned_nodes` from `web_toc.parsing.owner_resolution`; `WebNode`.
- Produces: `extract_notes(content: dict, citations: set[str], fallback_citation: str) -> list[tuple[str, WebNode]]` — Note nodes with `type="Note"`, `identifier="A-<number>"`, `heading=identifier`, `title`, `content` (paragraph + list-item text; tables/figures excluded), `citation=<note id>`.

- [ ] **Step 1: Write failing tests** — `tests/test_web_toc_note_extractor.py`:

```python
from web_toc.parsing.note_extractor import extract_notes

APPENDIX = {
    "id": "nbc.divA.part1.appendix",
    "type": "part_appendix",
    "application_notes": [
        {
            "id": "nbc.divA.part1.appendix.appnote2",
            "type": "application_note",
            "number": "1.1.1.1.(3)",
            "title": "Factory-Constructed Buildings.",
            "content": [
                {"type": "paragraph", "id": "p1", "content": "The Code applies."},
                {
                    "type": "paragraph",
                    "id": "p2",
                    "content": "It covers:",
                    "lists": [{"type": "bulleted", "items": [{"id": "i1", "content": "suites,"}]}],
                },
                {"id": "f1", "type": "figure", "title": "Fig", "graphic": {"src": "x"}},
                {"id": "t1", "type": "table", "title": "Tbl",
                 "structure": {"body_rows": [{"cells": [{"content": "cell text"}]}]}},
            ],
        },
        {"id": "nbc.divA.part1.appendix.appnote9", "type": "application_note", "title": "No number"},
    ],
}
CITATIONS = {"nbc.divA.part1.appendix"}


def test_extracts_note_with_official_number_owner_and_text():
    owner, note = extract_notes(APPENDIX, CITATIONS, "fallback")[0]

    assert owner == "nbc.divA.part1.appendix"
    assert note.type == "Note"
    assert note.identifier == "A-1.1.1.1.(3)"
    assert note.heading == "A-1.1.1.1.(3)"
    assert note.citation == "nbc.divA.part1.appendix.appnote2"
    assert note.title == "Factory-Constructed Buildings."
    assert note.content == "The Code applies. It covers: suites,"


def test_note_without_number_gets_empty_identifier():
    _, note = extract_notes(APPENDIX, CITATIONS, "fallback")[1]
    assert note.identifier == ""


def test_owner_falls_back_when_no_citation_matches():
    owner, _ = extract_notes(APPENDIX, set(), "fallback")[0]
    assert owner == "fallback"


def test_content_without_notes_yields_nothing():
    assert extract_notes({"id": "nbc.divA.part1.sect1"}, CITATIONS, "x") == []
```

In `tests/test_build_web_toc.py` add a test (same patch stack as `test_run_wires_pipeline_and_writes_images_from_every_content_bearing_node`, plus `@patch("build_web_toc.extract_tables")`) where `fetch_content` returns `{"id": "nbc.divA.part1.appendix", "application_notes": [{"id": "nbc.divA.part1.appendix.appnote2", "type": "application_note", "number": "1.1.1.1.(3)", "title": "T"}]}` for a `part_appendix` leaf (`citation="nbc.divA.part1.appendix"`, `identifier=""`), and assert:
  - the leaf's children contain one `Note` with identifier `A-1.1.1.1.(3)`;
  - `mock_extract_tables` and `mock_extract_images` were called with a citations set that **includes** `"nbc.divA.part1.appendix.appnote2"` (so appnote tables/figures resolve to the Note).

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_toc_note_extractor.py tests/test_build_web_toc.py -q`
Expected: FAIL — `ModuleNotFoundError: web_toc.parsing.note_extractor`.

- [ ] **Step 3: Implement** — `src/web_toc/parsing/note_extractor.py`:

```python
"""Walks a part/division appendix content JSON for the site's
{"type": "application_note", "number": "1.1.1.1.(3)", ...} entries and builds
one Note WebNode per note - the web counterpart of the PDF's
"A-1.1.1.1.(3) ..." Note nodes. Owner resolution is the same strip-and-match
used for figures and tables."""

from web_toc.domain.models import WebNode
from web_toc.parsing.owner_resolution import resolve_owner

_NON_TEXT_TYPES = frozenset({"table", "figure"})


def _walk_notes(node):
    if isinstance(node, dict):
        if node.get("type") == "application_note":
            yield node
        for value in node.values():
            yield from _walk_notes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_notes(item)


def _dict_text_parts(node: dict):
    if node.get("type") in _NON_TEXT_TYPES:
        return
    if isinstance(node.get("content"), str):
        yield node["content"]
    for key in ("content", "lists", "items"):
        yield from _text_parts(node.get(key))


def _text_parts(node):
    if isinstance(node, dict):
        yield from _dict_text_parts(node)
    elif isinstance(node, list):
        for item in node:
            yield from _text_parts(item)


def _note_node(note: dict) -> WebNode:
    number = note.get("number", "")
    identifier = f"A-{number}" if number else ""
    return WebNode(
        type="Note",
        identifier=identifier,
        citation=note["id"],
        title=note.get("title", ""),
        path="",
        content=" ".join(_text_parts(note.get("content", []))).strip(),
        heading=identifier,
    )


def extract_notes(
    content: dict, citations: set[str], fallback_citation: str
) -> list[tuple[str, WebNode]]:
    return [
        (resolve_owner(note["id"], citations, fallback_citation), _note_node(note))
        for note in _walk_notes(content)
        if note.get("id")
    ]
```

`src/build_web_toc.py` — import `from web_toc.parsing.note_extractor import extract_notes` and `from web_toc.parsing.owner_resolution import attach_owned_nodes`; replace the extraction part of `run` with helpers (keeps `run` ≤ 20 lines):

```python
def _fetched(targets, contents):
    for (node, url), content in zip(targets, contents, strict=True):
        if content is None:
            print(f"  skipped (no content at {url})", file=sys.stderr)
            continue
        yield node, content


def _attach_notes(root, fetched, citations: set[str]) -> set[str]:
    """Notes go in first so an appnote's own tables/figures resolve to the
    Note rather than its part_appendix. Returns the widened citation set."""
    notes = [
        owned for node, content in fetched for owned in extract_notes(content, citations, node.citation)
    ]
    attach_owned_nodes(root, notes)
    return citations | {note.citation for _, note in notes}


def _extract_owned(fetched, citations: set[str]):
    images, owned_tables, owned_sentences = [], [], []
    for node, content in fetched:
        images.extend(extract_images(content, citations, node.citation))
        owned_tables.extend(extract_tables(content, citations, node.citation))
        owned_sentences.extend(extract_body(content, citations, node.citation))
    return images, owned_tables, owned_sentences
```

and inside `run`, after `contents = await asyncio.gather(...)`:

```python
        fetched = list(_fetched(targets, contents))
        citations = _attach_notes(root, fetched, citations)
        images, owned_tables, owned_sentences = _extract_owned(fetched, citations)

        attach_tables(root, owned_tables)
        attach_body(root, owned_sentences)
```

(the existing `assign_unified_numbers(...)` call stays until Task 7).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_web_toc_note_extractor.py tests/test_build_web_toc.py -q`
Expected: new tests PASS; the old `unified_number` asserts in `test_build_web_toc.py` still pass or fail only because of Task 1 — they are updated in Task 7.

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/note_extractor.py src/build_web_toc.py tests/test_web_toc_note_extractor.py tests/test_build_web_toc.py
git commit -m "feat(web_toc): extract appendix Notes and attach them before tables/figures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Web numbering rules, image numbers, wiring

**Files:**
- Rewrite: `src/web_toc/parsing/numbering_config.py`
- Modify: `src/build_web_toc.py`
- Rewrite: `tests/test_web_toc_numbering_config.py`
- Modify: `tests/test_build_web_toc.py` (expected keys)
- Create: `tests/test_cross_source_numbering.py`

**Interfaces:**
- Consumes: Task 1 API; `MO_TOC_RULES`/`MO_TOC_SCOPE_TYPES` (Task 4) in the cross-source test.
- Produces: `WEB_TOC_RULES`, `WEB_TOC_SCOPE_TYPES`.

- [ ] **Step 1: Write failing tests**

`tests/test_web_toc_numbering_config.py` (replace):

```python
from shared.numbering import Rule
from web_toc.parsing.numbering_config import WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES


def test_official_number_levels_are_absolute():
    for level in ("part", "section", "subsection", "article", "Note"):
        assert WEB_TOC_RULES[level] == Rule("absolute")


def test_chain_restarting_levels():
    assert WEB_TOC_RULES["volume"] == Rule("root", "V")
    assert WEB_TOC_RULES["division"] == Rule("root", fallback="FM")
    assert WEB_TOC_RULES["division_appendix"] == Rule("root", "App")


def test_body_notes_and_table_levels():
    assert WEB_TOC_RULES["Sentence"] == Rule("child")
    assert WEB_TOC_RULES["Clause"] == Rule("suffix")
    assert WEB_TOC_RULES["Subclause"] == Rule("suffix")
    assert WEB_TOC_RULES["part_appendix"] == Rule("literal", "Notes")
    assert WEB_TOC_RULES["spectables"] == Rule("ordinal", "Spec")
    assert WEB_TOC_RULES["index"] == Rule("ordinal", "Idx")
    assert WEB_TOC_RULES["conversions"] == Rule("ordinal", "Conv")
    assert WEB_TOC_RULES["Table"] == Rule("ordinal", "Tbl", scoped=True)
    assert WEB_TOC_RULES["Row"] == Rule("ordinal", "Row")
    assert WEB_TOC_RULES["Cell"] == Rule("ordinal", "Col")


def test_scope_types():
    assert {"article", "Note", "part_appendix", "spectables"} <= WEB_TOC_SCOPE_TYPES
```

`tests/test_cross_source_numbering.py` — the spec's "same article, same keys" guarantee:

```python
from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.numbering_config import MO_TOC_RULES, MO_TOC_SCOPE_TYPES
from shared.numbering import assign_unified_numbers
from web_toc.domain.models import WebNode
from web_toc.parsing.numbering_config import WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES


def _pdf(node_type, identifier, children=()):
    return Node(type=node_type, identifier=identifier, citation=f"pdf-{node_type}-{identifier}",
                title="", page=1, end_page=1, bbox=BBox(0, 0, 0, 0), children=list(children))


def _web(node_type, identifier, children=()):
    return WebNode(type=node_type, identifier=identifier, citation=f"web-{node_type}-{identifier}",
                   title="", path="", children=list(children))


def _keys(node):
    yield node.type.lower(), node.unified_number
    for child in node.children:
        yield from _keys(child)


def test_part_9_gets_identical_keys_although_the_web_puts_it_in_volume_2():
    pdf_table = _pdf("Table", "9.10.18.2.", [_pdf("Row", "Row1", [_pdf("Cell", "Col1")])])
    pdf_article = _pdf("Article", "9.10.18.2.", [
        _pdf("Sentence", "(2)", [_pdf("Clause", "(a)"), pdf_table]),
    ])
    pdf_notes = _pdf("NotesContainer", "9", [_pdf("Note", "A-9.10.18.2.(2)")])
    pdf_part = _pdf("Part", "9", [
        _pdf("Section", "9.10.", [_pdf("Subsection", "9.10.18.", [pdf_article])]), pdf_notes,
    ])
    pdf_volume = _pdf("Volume", "Volume", [_pdf("Division", "B", [pdf_part])])

    web_table = _web("Table", "table1", [_web("Row", "row1", [_web("Cell", "col1")])])
    web_article = _web("article", "9.10.18.2", [
        _web("Sentence", "(2)", [_web("Clause", "(a)")]), web_table,
    ])
    web_notes = _web("part_appendix", "", [_web("Note", "A-9.10.18.2.(2)")])
    web_part = _web("part", "9", [
        _web("section", "9.10", [_web("subsection", "9.10.18", [web_article])]), web_notes,
    ])
    web_volume2 = _web("volume", "2", [_web("division", "B", [web_part])])

    assign_unified_numbers([pdf_volume], MO_TOC_RULES, MO_TOC_SCOPE_TYPES)
    assign_unified_numbers([web_volume2], WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES)

    pdf_keys = {key for _, key in _keys(pdf_volume.children[0])}
    web_keys = {key for _, key in _keys(web_volume2.children[0])}
    assert pdf_keys == web_keys
    assert "B.9.10.18.2.Tbl1.Row1.Col1" in web_keys
    assert "B.9.Notes" in web_keys
    assert "B.A-9.10.18.2.(2)" in web_keys
```

`tests/test_build_web_toc.py`: in the existing tests, change the expected keys to the new scheme — the section leaf with identifier `"1.1"` and no division above it now numbers `"1.1"` (was `"1"`), its table `"1.1.Tbl1"` (was `"1.Tbl1"`), sentence `"1.1.(1)"`, clause `"1.1.(1)(a)"`. Add `@patch("build_web_toc.number_images")` to one wiring test and assert it is called once with `(images, <dict>)` after `assign_unified_numbers`, where `images` is the list `extract_images` produced.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_toc_numbering_config.py tests/test_cross_source_numbering.py tests/test_build_web_toc.py -q`
Expected: FAIL — `ImportError: cannot import name 'WEB_TOC_RULES'`.

- [ ] **Step 3: Implement**

`src/web_toc/parsing/numbering_config.py` (replace):

```python
"""web_toc's cross-source numbering rules - the web counterpart of
mo_toc.parsing.numbering_config, built so both produce the same key for the
same node. The synthetic "root" wrapper is never numbered (only its children
are passed in)."""

from shared.numbering import Rule

_ABSOLUTE = Rule("absolute")

WEB_TOC_RULES: dict[str, Rule] = {
    "volume": Rule("root", "V"),
    # The unnumbered "Preface" division is the PDF's front matter.
    "division": Rule("root", fallback="FM"),
    "division_appendix": Rule("root", "App"),
    "part": _ABSOLUTE,
    "section": _ABSOLUTE,
    "subsection": _ABSOLUTE,
    "article": _ABSOLUTE,
    "Note": _ABSOLUTE,
    "Sentence": Rule("child"),
    "Clause": Rule("suffix"),
    "Subclause": Rule("suffix"),
    "part_appendix": Rule("literal", "Notes"),
    "spectables": Rule("ordinal", "Spec"),
    "index": Rule("ordinal", "Idx"),
    "conversions": Rule("ordinal", "Conv"),
    "Table": Rule("ordinal", "Tbl", scoped=True),
    "Row": Rule("ordinal", "Row"),
    "Cell": Rule("ordinal", "Col"),
}

WEB_TOC_SCOPE_TYPES: frozenset[str] = frozenset(
    {"part", "section", "subsection", "article", "part_appendix", "Note", "spectables",
     "index", "conversions"}
)
```

`src/build_web_toc.py`: imports become

```python
from shared.numbering import assign_unified_numbers, number_images
from web_toc.parsing.numbering_config import WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES
```

and the numbering call becomes

```python
        scope_by_citation = assign_unified_numbers(
            root.children, WEB_TOC_RULES, WEB_TOC_SCOPE_TYPES
        )
        number_images(images, scope_by_citation)
```

(keep the existing comment above it about numbering after attach).

- [ ] **Step 4: Run to verify pass**

Run: `pytest -q`
Expected: whole default suite PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/numbering_config.py src/build_web_toc.py tests/
git commit -m "feat(web_toc): number the web tree and images with cross-source keys

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `compare_unified.py` report

**Files:**
- Create: `src/compare_unified.py`
- Create: `tests/test_compare_unified.py`
- Modify: `CLAUDE.md` (add `src/compare_unified.py` to the item-2 description and to the Definition-of-done scope list)

**Interfaces:**
- Produces: `LEVEL_OF`, `LEVELS`, `LevelCount(level, pdf, web, both)` with `.pdf_only`/`.web_only`, `collect_keys(tree, images)`, `level_counts(pdf_keys, web_keys)`, `comparable_text(node)`, `text_mismatches(pdf_nodes, web_nodes)`, `format_report(counts)`, `main(argv=None)`.

- [ ] **Step 1: Write failing tests** — `tests/test_compare_unified.py`:

```python
import json

from compare_unified import (
    LevelCount,
    collect_keys,
    comparable_text,
    format_report,
    level_counts,
    main,
    text_mismatches,
)

PDF_TREE = {"type": "Volume", "unified_number": "V1", "children": [
    {"type": "Part", "unified_number": "A.1", "title": "Compliance", "heading": "Part 1",
     "children": [
         {"type": "NotesContainer", "unified_number": "A.1.Notes", "title": "Notes to Part 1",
          "heading": "Notes to Part 1", "children": []},
         {"type": "Article", "unified_number": "A.1.1.1.1", "title": "Scope", "children": []},
     ]},
]}
WEB_TREE = {"type": "root", "children": [
    {"type": "part", "unified_number": "A.1", "title": "Part 1 - Compliance", "heading": "Part 1",
     "children": [
         {"type": "part_appendix", "unified_number": "A.1.Notes", "title": "Notes to Part 1",
          "heading": "Notes to Part 1", "children": []},
         {"type": "Sentence", "unified_number": "A.1.1.1.1.(1)",
          "content": "a [REF:term:bldng:building]", "children": []},
     ]},
]}


def test_collect_keys_groups_by_level_and_skips_unnumbered():
    keys = collect_keys(PDF_TREE, [{"unified_number": "A.1.1.1.1.Fig1"}, {"unified_number": ""}])
    assert set(keys["part"]) == {"A.1"}
    assert set(keys["notes"]) == {"A.1.Notes"}
    assert set(keys["image"]) == {"A.1.1.1.1.Fig1"}
    assert keys["sentence"] == {}


def test_level_counts_both_and_only():
    counts = {c.level: c for c in level_counts(collect_keys(PDF_TREE, []), collect_keys(WEB_TREE, []))}
    assert counts["notes"] == LevelCount("notes", 1, 1, 1)
    assert (counts["article"].pdf_only, counts["article"].web_only) == (1, 0)
    assert (counts["sentence"].pdf_only, counts["sentence"].web_only) == (0, 1)


def test_comparable_text_strips_heading_refs_and_case():
    assert comparable_text({"title": "Part 1 - Compliance", "heading": "Part 1"}) == "compliance"
    assert comparable_text({"content": "A  [REF:term:bldng:Building]"}) == "a building"
    assert comparable_text({}) == ""


def test_text_mismatches_only_reports_matched_keys_that_differ():
    pdf = {"k1": {"title": "Scope"}, "k2": {"title": "X"}, "only": {"title": "Y"}}
    web = {"k1": {"title": "1.1.1.1 Scope", "heading": "1.1.1.1"}, "k2": {"title": "Z"}}
    assert text_mismatches(pdf, web) == [("k2", "x", "z")]


def test_format_report_has_header_and_one_row_per_level():
    report = format_report([LevelCount("part", 15, 15, 14)])
    lines = report.splitlines()
    assert lines[0].split() == ["level", "pdf", "web", "both", "pdf-only", "web-only"]
    assert lines[1].split() == ["part", "15", "15", "14", "1", "1"]


def test_main_prints_report_and_diffs(tmp_path, capsys):
    pdf_path, web_path = tmp_path / "pdf.json", tmp_path / "web.json"
    pdf_path.write_text(json.dumps({"volume": PDF_TREE, "images": []}))
    web_path.write_text(json.dumps({"tree": WEB_TREE, "images": []}))

    main(["--pdf", str(pdf_path), "--web", str(web_path), "--diff"])

    out = capsys.readouterr().out
    assert "notes" in out
    assert "text mismatches" not in out  # Part/Notes titles agree once headings are stripped
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_compare_unified.py -q`
Expected: FAIL — `ModuleNotFoundError: compare_unified`.

- [ ] **Step 3: Implement** — `src/compare_unified.py`:

```python
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

LEVEL_OF = {
    "Volume": "volume", "volume": "volume",
    "Division": "division", "division": "division",
    "Part": "part", "part": "part",
    "Section": "section", "section": "section",
    "Subsection": "subsection", "subsection": "subsection",
    "Article": "article", "article": "article",
    "Sentence": "sentence", "Clause": "clause", "Subclause": "subclause",
    "NotesContainer": "notes", "part_appendix": "notes",
    "Note": "note",
    "Appendix": "appendix", "division_appendix": "appendix",
    "Table": "table", "Row": "row", "Cell": "cell",
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


def collect_keys(tree: dict, images: list[dict]) -> dict[str, dict[str, dict]]:
    keys: dict[str, dict[str, dict]] = {level: {} for level in LEVELS}
    for node in _walk(tree):
        level = LEVEL_OF.get(node["type"])
        if level and node.get("unified_number"):
            keys[level][node["unified_number"]] = node
    keys["image"] = {i["unified_number"]: i for i in images if i.get("unified_number")}
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
        text = text[len(heading) :].lstrip(" -")
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
```

`CLAUDE.md`: in item 2's web-TOC paragraph add one sentence — "`src/compare_unified.py` compares the two indexes by `unified_number` (keys built from the code's own numbering, identical in both files for the same node) and reports per-level agreement; `--diff` lists matched keys whose text differs." — and add `src/compare_unified.py` to the Definition-of-done scope list next to `src/build_web_pages.py`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_compare_unified.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/compare_unified.py tests/test_compare_unified.py CLAUDE.md
git commit -m "feat: add compare_unified.py cross-source key report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Full rebuild, verification, definition of done

**Files:** no source changes expected; fix-ups only if a check fails.

- [ ] **Step 1: Definition of done**

```bash
ruff check --fix . && ruff format .
radon cc -s -n B src tests
vulture .
pytest --cov=. -q
```

Expected: ruff clean, radon prints nothing, vulture no new findings, all tests pass. Fix anything reported (radon C → split the function).

- [ ] **Step 2: Rebuild the PDF index** (long: full 1685-page PDF)

```bash
python3 src/build_mo_toc.py "/Users/rajeev/Projects/PlayGround/data/MO Package BCBC MRK signed.pdf"
```

Expected: writes `output/bcbc_pdf.json` in the worktree; no `ValueError` from `nest_notes_under_parts`.

- [ ] **Step 3: Rebuild the web index** (network)

```bash
python3 src/build_web_toc.py
```

Expected: writes `output/bcbc_web.json`.

- [ ] **Step 4: Spot-check the Notes requirement**

```bash
python3 src/compare_unified.py --diff --limit 15
```

Expected:
- `notes` row: pdf 12, web 12, both 12 — and no `notes: … text mismatches` block (all titles "Notes to Part N").
- `part` both ≥ 14 of 15 (Part 2 "Reserved" wording aside); `section`/`subsection`/`article` both close to the smaller of the two counts — far above today's 61/189/951.
- `row`/`cell` both no longer 0.
- Record the full report output for the PR description, including remaining pdf-only/web-only counts per level and the first few text mismatches (these are genuine parse differences to list, not to fix in this PR).

- [ ] **Step 5: Viewer smoke check**

```bash
python3 -m uvicorn serve_mo_toc:app --app-dir src --port 8001
```

(Or however `src/serve_mo_toc.py` documents its launch — check its module docstring.) In the PDF tab, expand Division A → Part 1 and confirm "Notes to Part 1" appears as the last child after its Sections, with its unified number `A.1.Notes`. Stop the server.

- [ ] **Step 6: Commit any fix-ups, push, open the PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: cross-source unified numbering for bcbc_pdf.json and bcbc_web.json" --body "<summary + compare report from Step 4>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
