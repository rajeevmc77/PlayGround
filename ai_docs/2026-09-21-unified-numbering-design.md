# Unified Document-Level Numbering — Design

**Status:** Approved by user, ready for implementation planning.

## 1. Problem

`mo_toc` (PDF-based index) and `web_toc` (website-based index) each already carry a
`citation`/`identifier` pair per node, but those are the *source* numbering — the PDF's
own dotted clause references (e.g. `A-1.1.1.1.(3)(a)`) and the website's own citation
tokens (e.g. `nbc.divB.part3.sect1.subsect1.art1`). Neither is a uniform, purely
positional scheme across all nine conceptual document levels:

```
volume.division.part.section.subsection.article.sentence.clause.subclause
```

The request is to add exactly that: a new, additive `unified_number` per tree node,
computed independently for each tree, in the same dotted format, for both the PDF tab
and the Web tab.

## 2. Scope decisions (confirmed with user)

1. **Numbering scope — independent per tree.** Each tree computes its own numbering
   from its own structure. The same real-world section (e.g. Division B, Part 9) is
   **not** guaranteed to carry the same `unified_number` in both tabs, because the two
   trees are shaped differently (see §3). This was the explicit, accepted trade-off in
   exchange for a much simpler and lower-risk implementation.
2. **Non-level nodes — numbered with a marker.** Node types that don't correspond to
   one of the nine canonical levels (`FrontMatter`, `Appendix` chain, `BackMatter`,
   `NotesContainer`/`Note`, `TableGroup` in `mo_toc`; `part_appendix`,
   `division_appendix`, `index`, `conversions`, `spectables` in `web_toc`) still get a
   `unified_number`, built from a short type marker plus their own positional count
   among same-type siblings (e.g. `"1.2.App1"`).
3. **Surface — JSON output *and* viewer display.** The field is added to both
   `output/mo_toc.json` / `output/web_toc.json`, and shown in the viewer next to each
   tree row (Table of Contents tab, Table of Images tab, BC Code (Web) tab, and the web
   image detail panel).

Explicitly out of scope: `output/mo_toc.md` (markdown writer) and the flat
Table/Figure caption index — captions and images are not "document levels," and
markdown output wasn't one of the chosen surfaces.

## 3. Verified current tree shapes

Confirmed by loading the already-built `output/mo_toc.json` and `output/web_toc.json`
in this session.

**`mo_toc` node types** (from `Node.type`, PyMuPDF-parsed PDF):
`Volume, FrontMatter, Division, Part, Section, Subsection, Article, Sentence, Clause,
Subclause, NotesContainer, Note, Appendix, AppendixPart, AppendixSection,
AppendixArticle, BackMatter, TableGroup`

The tree has a single `Volume` root (this is the merged "MO Package" PDF — there is no
second volume). `Division` (A/B/C) sits directly under that one `Volume`, and `Part 9`
(Housing) lives under `Division B` alongside every other Part — there is no split.

**`web_toc` node types** (from `WebNode.type`, website navigation tree):
`root, volume, division, part, section, subsection, article, part_appendix,
division_appendix, index, conversions, spectables`

The tree has a synthetic `root` wrapper (not a real content node — added by
`build_tree()` to hold the navigation JSON's top-level `tree` array) whose children are
**two** `volume` nodes. `Part 9` (Housing) lives under the *second* `volume`, as its own
`division` (`nbc.divBV2`), not under the first volume's `Division B`. `web_toc` also
never descends past `article` — `sentence`/`clause`/`subclause` don't exist as
navigation-tree nodes on the website (that granularity lives only in each article's own
body content, which isn't part of this tree).

This confirms why independent per-tree numbering (§2.1) was the right call: the trees
disagree on where "Part 9" sits, so any numbering that walks parent→child positions
will assign it different numbers in each tree regardless of algorithm.

## 4. Domain model changes

`src/mo_toc/domain/models.py`:
```python
@dataclass
class Node:
    type: str
    identifier: str
    citation: str
    title: str
    page: int
    end_page: int
    bbox: BBox
    children: list["Node"] = field(default_factory=list)
    unified_number: str = ""
```

`src/web_toc/domain/models.py`:
```python
@dataclass
class WebNode:
    type: str
    identifier: str
    citation: str
    title: str
    path: str
    children: list["WebNode"] = field(default_factory=list)
    unified_number: str = ""
```

Both are additive fields with a default, appended after `children` — existing
positional-argument call sites in both codebases (and their tests) keep working
unchanged.

## 5. Shared numbering algorithm

New file `src/shared/numbering.py` (plus `src/shared/__init__.py`) — the first code
shared between the two otherwise fully independent packages. It is justified here
because the algorithm is identical and depends on nothing package-specific: it duck-types
on any object exposing `.type`, `.children`, and a settable `.unified_number`.

```python
def assign_unified_numbers(
    nodes: list, type_to_marker: dict[str, str | None], parent_number: str = ""
) -> None:
    """Assign a dotted unified_number to every node in `nodes` and its descendants,
    in place. `nodes` is the list of top-level nodes to number (siblings at the root
    of whatever tree is being numbered — NOT a single root object)."""
    counters: dict[str, int] = {}
    for node in nodes:
        counters[node.type] = counters.get(node.type, 0) + 1
        position = counters[node.type]
        marker = type_to_marker.get(node.type, node.type)
        segment = str(position) if type_to_marker.get(node.type, "") is None else f"{marker}{position}"
        node.unified_number = f"{parent_number}.{segment}" if parent_number else segment
        assign_unified_numbers(node.children, type_to_marker, node.unified_number)
```

(Exact segment-building logic above is illustrative of behavior — the implementation
plan will write it more cleanly, e.g. by branching on `node.type in type_to_marker and
type_to_marker[node.type] is None` first. Behavior contract, precisely:)

- **Position** = 1-based index of this node among *siblings sharing the exact same
  `type` string*, under the same immediate parent list. Siblings of a different type do
  not affect each other's count.
- **Canonical level** (type maps to `None` in `type_to_marker`): segment is just the
  position, e.g. `"3"`.
- **Marker type** (type maps to a non-`None` string): segment is `f"{marker}{position}"`,
  e.g. `"App1"`, `"Note3"`.
- **Unmapped type** (not a key in `type_to_marker` at all): falls back to using the
  type string itself as the marker (e.g. an unrecognized type `"Foo"` under a parent
  numbered `"1.2"` becomes `"1.2.Foo1"`). This is graceful degradation, not an error —
  consistent with the rest of this codebase's handling of unexpected data.
- Each node's own `unified_number` is `f"{parent_number}.{segment}"`, or just `segment`
  when `parent_number` is `""` (top-level nodes).
- Recursion always descends into `node.children`, regardless of whether the node itself
  was a canonical or marker type.
- Position numbers are plain decimal, no zero-padding (`"9"`, not `"09"`), and the
  final string never has a leading or trailing dot.

## 6. Per-package marker tables

Package-specific knowledge stays local to each package, not in `src/shared/`.

`src/mo_toc/parsing/numbering_config.py` (new):
```python
MO_TOC_TYPE_MARKERS: dict[str, str | None] = {
    "Volume": None,
    "Division": None,
    "Part": None,
    "Section": None,
    "Subsection": None,
    "Article": None,
    "Sentence": None,
    "Clause": None,
    "Subclause": None,
    "FrontMatter": "FM",
    "BackMatter": "BM",
    "Appendix": "App",
    "AppendixPart": "AppPt",
    "AppendixSection": "AppSec",
    "AppendixArticle": "AppArt",
    "NotesContainer": "Notes",
    "Note": "Note",
    "TableGroup": "Tbl",
}
```

`src/web_toc/parsing/numbering_config.py` (new):
```python
WEB_TOC_TYPE_MARKERS: dict[str, str | None] = {
    "volume": None,
    "division": None,
    "part": None,
    "section": None,
    "subsection": None,
    "article": None,
    "part_appendix": "App",
    "division_appendix": "App",
    "index": "Idx",
    "conversions": "Conv",
    "spectables": "Spec",
}
```

`root` is deliberately absent from `WEB_TOC_TYPE_MARKERS` — it is never passed into
`assign_unified_numbers` as a node to number (see §7); only its children are.

## 7. Wiring into the two build pipelines

`src/build_mo_toc.py::run()` — after tree construction, before writing output:
```python
volume, captions = build_tree(source)
assign_unified_numbers([volume], MO_TOC_TYPE_MARKERS)
```
(The PDF tree's outermost object is the single `Volume` node itself, not a wrapper list
— so it's passed as a one-element list, giving it `unified_number = "1"`.)

`src/build_web_toc.py::run()` — after tree construction, before writing output:
```python
root = build_tree(nav_data)
assign_unified_numbers(root.children, WEB_TOC_TYPE_MARKERS)
```
(`root` is the synthetic wrapper from `build_tree()` — it keeps `unified_number = ""`
and is excluded from numbering; its two `volume` children become `"1"` and `"2"`.)

Both call sites run before `write_json(...)`, so the field is present in output as soon
as it's computed — no writer changes needed, since both writers already serialize via
`dataclasses.asdict(...)`, which picks up the new field automatically.

## 8. Output changes

`output/mo_toc.json` (`volume` object, recursively) and `output/web_toc.json` (`tree`
object, recursively): every node gains `"unified_number": "<string>"`. Example (from
the real tree walked in §3):

```json
{"type": "Division", "identifier": "B", "citation": "B", "unified_number": "1.2", ...}
```

No existing keys are removed, renamed, or change meaning.

## 9. Viewer changes

`src/mo_toc/web/static/viewer.js` — add one helper, used at the 4 existing spots that
currently render `` `${node.type} ${node.identifier} ${node.title}` `` (or the
`ownerNode` equivalent):

```js
function formatNodeLabel(node) {
  return [node.unified_number, node.type, node.identifier, node.title]
    .filter(Boolean)
    .join(" ");
}
```

Call sites to update (all currently build the same three-part string inline):
- `renderNode` (~line 22, Table of Contents tab)
- `renderImageTreeNode` (~line 113, Table of Images tab)
- `renderWebTreeNode` (~line 206, BC Code (Web) tab)
- the owner-node label built around ~line 185 (web image detail panel)

No HTML/CSS changes are required — this only changes what text is written into the
existing row elements.

## 10. Testing strategy

New:
- `tests/test_numbering.py` — unit tests for `assign_unified_numbers` against small
  synthetic node-like objects (a minimal local dataclass/stub, not `Node`/`WebNode`, to
  keep the shared module's tests independent of either package): multi-level plain
  numbering; sibling counters scoped per-type (mixed-type siblings don't interfere with
  each other's count); marker-prefixed segments; nested marker chains (marker type whose
  children are also marker types); unmapped-type fallback; empty `children` (leaf,
  no recursion crash); multiple same-type nodes at the top level (e.g. two `volume`
  nodes) numbered `"1"`, `"2"`.
- Extend `tests/test_build_mo_toc.py` and `tests/test_build_web_toc.py`: assert
  `run()` produces a tree (via the written JSON) where sampled nodes carry the expected
  `unified_number`.
- Extend `tests/test_web_toc_domain_models.py` / the `mo_toc` domain model test (if one
  exists) to cover the new field's default.

Existing tests for `Node`, `WebNode`, `build_tree`, both `json_writer`s, and the viewer
routes are expected to keep passing unmodified — the field is additive with a default,
and JSON serialization is automatic via `dataclasses.asdict`.

No automated JS test suite exists in this repo today; the viewer change is verified by
running `python src/serve_mo_toc.py` and visually confirming the unified number appears
in all three tree tabs and the web image detail panel, per this project's existing
practice for UI work.

## 11. Definition of done

Same checklist as the rest of this repo's new work, scoped to the files this design
touches plus the two build entry points and `tests/`:
```bash
ruff check --fix src/shared src/mo_toc src/web_toc src/build_mo_toc.py src/build_web_toc.py tests
ruff format src/shared src/mo_toc src/web_toc src/build_mo_toc.py src/build_web_toc.py tests
radon cc -s -n B src/shared src/mo_toc src/web_toc src/build_mo_toc.py src/build_web_toc.py tests
vulture src/shared src/mo_toc src/web_toc src/build_mo_toc.py src/build_web_toc.py tests
pytest --cov=src/shared --cov=src/mo_toc --cov=src/web_toc --cov=src.build_mo_toc --cov=src.build_web_toc
```
