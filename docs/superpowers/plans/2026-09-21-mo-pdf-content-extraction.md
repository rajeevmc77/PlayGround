# mo_pdf.json Content Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `output/mo_toc.json` as `output/mo_pdf.json`: every Sentence/Clause/Subclause carries its complete multi-line text (`content`, marker-stripped), tables become structured Table→Row→Cell tree children instead of invisible/misclassified-as-image content, and images/figures attach to the most precise node that owns them (down to Sentence/Clause/Subclause, including inline formula images).

**Architecture:** Additive changes to the existing `src/mo_toc/` pipeline. `body_segmenter.py` is rewritten from a marker-line-only extractor into a single-pass "current owner" text accumulator. A new `table_extractor.py` module detects table grids from vector-drawn borders (`PdfSource.page_drawing_rects`), anchored to already-reliable Table captions, and builds Table→Row→Cell subtrees per page; a second pass stitches multi-page continuations and attaches each table to its resolved owner (Sentence/Clause/Article/etc.) in the already-built tree. `image_matcher.py`'s existing position-based ownership walk is generalized by removing its Sentence/Clause/Subclause exclusion. `json_writer.py` prunes `title`/`content` per node type on the way out.

**Tech Stack:** Python 3.11, pytest, dataclasses, PyMuPDF (via the existing `PdfSource` abstraction) — no new dependencies.

**Spec:** [ai_docs/2026-09-21-mo-pdf-content-design.md](../../../ai_docs/2026-09-21-mo-pdf-content-design.md)

## Global Constraints

- TDD strictly: failing test → minimum code to pass → refactor. Never weaken or delete an existing test.
- Functions ≤20 executable lines, cyclomatic complexity ≤6, nesting ≤2 levels.
- `ruff check --fix . && ruff format .`, `radon cc -s -n B .`, `vulture .`, `pytest --cov=.` must all be clean before the branch is considered done (scoped to `src/mo_toc/`, `src/build_mo_toc.py`, `src/mo_toc/web/`, `src/shared/`, `tests/` per `CLAUDE.md`).
- Work happens in an isolated git worktree (created via `superpowers:using-git-worktrees`); open a PR to merge back to `main`, then delete the worktree/branch.
- Real 1685-page-PDF tests are `slow`-marked and skipped by default (`pytest -q` already excludes them via `pyproject.toml`'s `addopts`).
- `title` vs `content` per type (from the spec): Sentence/Clause/Subclause/Cell use `content` only; Row uses neither; every other type (including Table) keeps `title` only. A pruned key is **absent** from JSON output, never `""`.

---

### Task 1: `Node.content` and `ImageAsset.title` fields

**Files:**
- Modify: `src/mo_toc/domain/models.py`
- Test: `tests/test_domain_models.py`

**Interfaces:**
- Produces: `Node.content: str = ""` (new field, after `unified_number`). `ImageAsset.title: str = ""` (new field, after `caption_title`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_domain_models.py` (import `Node`, `ImageAsset`, `BBox` from `mo_toc.domain.models` if not already imported at the top of the file):

```python
def test_node_content_defaults_to_empty_string():
    node = Node(
        type="Sentence",
        identifier="(1)",
        citation="A-1.1.1.1.(1)",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    assert node.content == ""


def test_node_content_can_be_set():
    node = Node(
        type="Sentence",
        identifier="(1)",
        citation="A-1.1.1.1.(1)",
        title="",
        content="Full sentence text.",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    assert node.content == "Full sentence text."


def test_image_asset_title_defaults_to_empty_string():
    image = ImageAsset(
        page=1, bbox=BBox(0, 0, 5, 5), width=5, height=5, phash=None,
        image_path="images/img_0.png",
    )
    assert image.title == ""


def test_image_asset_title_can_be_set():
    image = ImageAsset(
        page=1, bbox=BBox(0, 0, 5, 5), width=5, height=5, phash=None,
        image_path="images/img_0.png", title="Figure A-1.1.1.1.(6)",
    )
    assert image.title == "Figure A-1.1.1.1.(6)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_domain_models.py -v`
Expected: FAIL — `TypeError: Node.__init__() got an unexpected keyword argument 'content'` (and similarly for `ImageAsset.title`).

- [ ] **Step 3: Add the fields**

In `src/mo_toc/domain/models.py`, edit `Node`:

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
    content: str = ""
```

Edit `ImageAsset`:

```python
@dataclass
class ImageAsset:
    page: int
    bbox: BBox
    width: int
    height: int
    phash: str | None
    image_path: str
    owner_citation: str = ""
    caption_kind: str | None = None
    caption_identifier: str | None = None
    caption_title: str | None = None
    title: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_domain_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/domain/models.py tests/test_domain_models.py
git commit -m "feat(mo_toc): add Node.content and ImageAsset.title fields"
```

---

### Task 2: `json_writer.py` title/content pruning

**Files:**
- Modify: `src/mo_toc/output/json_writer.py`
- Test: `tests/test_json_writer.py`

**Interfaces:**
- Consumes: `Node.content` (Task 1).
- Produces: `write_json(...)` output JSON drops `content` for every node type except `{Sentence, Clause, Subclause, Cell}`, and drops `title` for `{Sentence, Clause, Subclause, Cell, Row}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_json_writer.py`:

```python
def test_write_json_drops_title_for_content_bearing_types(tmp_path):
    sentence = Node(
        type="Sentence", identifier="(1)", citation="A-1.1.1.1.(1)", title="",
        content="Full text.", page=1, end_page=1, bbox=BBox(0, 0, 0, 0),
    )
    article = Node(
        type="Article", identifier="1.1.1.1.", citation="A-1.1.1.1.", title="A title",
        page=1, end_page=1, bbox=BBox(0, 0, 0, 0), children=[sentence],
    )
    out_path = tmp_path / "out.json"
    write_json(article, [], [], str(out_path))
    payload = json.loads(out_path.read_text())

    sentence_json = payload["volume"]["children"][0]
    assert "title" not in sentence_json
    assert sentence_json["content"] == "Full text."
    assert "content" not in payload["volume"]
    assert payload["volume"]["title"] == "A title"


def test_write_json_drops_both_title_and_content_for_row(tmp_path):
    row = Node(
        type="Row", identifier="Row1", citation="Table:1.1.(1)-Row1", title="",
        page=1, end_page=1, bbox=BBox(0, 0, 0, 0),
    )
    out_path = tmp_path / "out.json"
    write_json(row, [], [], str(out_path))
    payload = json.loads(out_path.read_text())
    assert "title" not in payload["volume"]
    assert "content" not in payload["volume"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_json_writer.py -v`
Expected: FAIL — `assert "title" not in sentence_json` fails because `title` is currently emitted as `""`.

- [ ] **Step 3: Implement pruning**

In `src/mo_toc/output/json_writer.py`, replace the file's contents:

```python
import dataclasses
import json
from pathlib import Path

from mo_toc.domain.models import Caption, ImageAsset, Node

_CONTENT_TYPES = {"Sentence", "Clause", "Subclause", "Cell"}
_NO_TITLE_TYPES = _CONTENT_TYPES | {"Row"}


def _prune_node(node_dict: dict) -> dict:
    if node_dict["type"] not in _CONTENT_TYPES:
        node_dict.pop("content", None)
    if node_dict["type"] in _NO_TITLE_TYPES:
        node_dict.pop("title", None)
    node_dict["children"] = [_prune_node(child) for child in node_dict["children"]]
    return node_dict


def write_json(
    volume: Node, captions: list[Caption], images: list[ImageAsset], out_path: str
) -> None:
    payload = {
        "volume": _prune_node(dataclasses.asdict(volume)),
        "captions": [dataclasses.asdict(c) for c in captions],
        "images": [dataclasses.asdict(i) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_json_writer.py -v`
Expected: PASS (including the two pre-existing tests in the file — `test_write_json_roundtrips_tree_shape` and `test_write_json_creates_parent_directories` — confirm they still pass since `Volume`/`Part` aren't in `_NO_TITLE_TYPES`).

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/output/json_writer.py tests/test_json_writer.py
git commit -m "feat(mo_toc): prune title/content keys per node type in json_writer"
```

---

### Task 3: `body_segmenter.py` full-content capture

**Files:**
- Modify: `src/mo_toc/parsing/body_segmenter.py`
- Test: `tests/test_body_segmenter.py`

**Interfaces:**
- Consumes: `Node.content` (Task 1).
- Produces: Sentence/Clause/Subclause nodes with `content` = complete, marker-stripped, multi-line text (space-joined); `title` stays `""`. `bbox` unions every same-page physical line belonging to that node. `segment_article_body(body_lines, article_citation, article_end_page) -> list[Node]` signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_body_segmenter.py` (reuses the file's existing `line()` helper):

```python
def test_sentence_content_is_marker_stripped():
    body = [line(5, 100, 50, "1) Fire protection shall conform to NFPA 303.")]
    sentences = segment_article_body(body, "B-2.16.2.1.", article_end_page=7)
    assert sentences[0].content == "Fire protection shall conform to NFPA 303."
    assert sentences[0].title == ""


def test_clause_content_includes_wrapped_continuation_line():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) except as permitted by the Fire Code, the installation, replacement, or"),
        line(5, 124, 60, "alteration of materials or equipment regulated by this Code,"),
        line(5, 136, 60, "b) next clause,"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    clause_a, clause_b = sentences[0].children
    assert clause_a.content == (
        "except as permitted by the Fire Code, the installation, replacement, or "
        "alteration of materials or equipment regulated by this Code,"
    )
    assert clause_a.title == ""
    assert clause_b.content == "next clause,"


def test_clause_bbox_unions_continuation_line_on_same_page():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) first physical line"),
        line(5, 124, 65, "second physical line, wider"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    clause_a = sentences[0].children[0]
    assert clause_a.bbox.y0 == 112
    assert clause_a.bbox.y1 == 124 + 10  # line() gives each PageLine bbox height 10
    assert clause_a.bbox.x0 == 60


def test_continuation_line_on_a_later_page_extends_content_not_bbox():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) first physical line on page 6"),
        line(6, 40, 60, "continues on the next page"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=8)
    clause_a = sentences[0].children[0]
    assert clause_a.content == "first physical line on page 6 continues on the next page"
    assert clause_a.bbox.y0 == 112


def test_sentence_own_continuation_line_before_first_clause_marker():
    body = [
        line(5, 100, 50, "1) This sentence wraps onto"),
        line(5, 112, 50, "a second physical line before any clause starts,"),
        line(5, 124, 60, "a) then the first clause."),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    sentence = sentences[0]
    assert sentence.content == (
        "This sentence wraps onto a second physical line before any clause starts,"
    )
    assert sentence.children[0].content == "then the first clause."


def test_subclause_content_and_ownership_after_a_new_clause_resets():
    body = [
        line(5, 100, 50, "1) intro:"),
        line(5, 112, 60, "a) clause a"),
        line(5, 124, 75, "iv) subclause under a"),
        line(5, 136, 60, "b) clause b, no subclauses"),
    ]
    sentences = segment_article_body(body, "A-1.1.1.1.", article_end_page=7)
    clause_a, clause_b = sentences[0].children
    assert clause_a.children[0].content == "subclause under a"
    assert clause_b.content == "clause b, no subclauses"
    assert clause_b.children == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_body_segmenter.py -v`
Expected: FAIL on the new tests — e.g. `assert sentences[0].content == "Fire protection..."` fails because `content` is currently `""` (title carries the raw marker-prefixed first line instead).

- [ ] **Step 3: Rewrite the marker/continuation logic**

In `src/mo_toc/parsing/body_segmenter.py`, replace `_marker_node`, `_add_markers_to_sentence`, and `_build_sentence` (lines 75-139 in the current file) with:

```python
def _union_bbox(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _marker_node(
    node_type: str, token: str, content: str, parent_citation: str,
    page_index: int, pline, end_page: int
) -> Node:
    identifier = f"({token.lower()})"
    page = page_index + 1
    return Node(
        type=node_type,
        identifier=identifier,
        citation=f"{parent_citation}{identifier}",
        title="",
        content=content,
        page=page,
        # end_page is inherited from the sentence/article boundary computed
        # before this marker's own page was known - clamp so it can't land
        # before this node's own start page (same class of bug as Fix 1).
        end_page=max(page, end_page),
        bbox=BBox(*pline.bbox),
    )


def _append_continuation(owner: Node, owner_start_page: int, page_index: int, pline) -> None:
    owner.content = f"{owner.content} {pline.text}".strip()
    if page_index == owner_start_page:
        owner.bbox = _union_bbox(owner.bbox, BBox(*pline.bbox))


def _add_markers_to_sentence(sentence: Node, group: list[BodyLine], end_page: int) -> None:
    clause_x, subclause_x = _clause_subclause_x0s(group)
    threshold = _sentence_threshold(clause_x, subclause_x)
    next_letter, prev_clause_x0, cur_clause = "a", None, None
    current_owner, current_owner_page = sentence, sentence.page - 1

    for page_index, pline in group[1:]:
        match = RE_MARKER.match(pline.text)
        if not match:
            _append_continuation(current_owner, current_owner_page, page_index, pline)
            continue
        token, kind = match.group(1), classify_marker(match.group(1))
        kind = _resolve_kind(kind, token, pline, next_letter, threshold, prev_clause_x0)
        if kind == "clause":
            cur_clause = _marker_node(
                "Clause", token, match.group(2), sentence.citation, page_index, pline, end_page
            )
            sentence.children.append(cur_clause)
            next_letter, prev_clause_x0 = _advance_clause_state(pline, token, next_letter)
            current_owner, current_owner_page = cur_clause, page_index
            continue
        if kind != "subclause" or cur_clause is None:
            continue
        subclause = _marker_node(
            "Subclause", token, match.group(2), cur_clause.citation, page_index, pline, end_page
        )
        cur_clause.children.append(subclause)
        current_owner, current_owner_page = subclause, page_index


def _build_sentence(group: list[BodyLine], article_citation: str, end_page: int) -> Node:
    first_page_index, first_line = group[0]
    match = RE_MARKER.match(first_line.text)
    token = match.group(1)
    sentence = Node(
        type="Sentence",
        identifier=f"({token})",
        citation=f"{article_citation}({token})",
        title="",
        content=match.group(2),
        page=first_page_index + 1,
        end_page=end_page,
        bbox=BBox(*first_line.bbox),
    )
    _add_markers_to_sentence(sentence, group, end_page)
    return sentence
```

`segment_article_body` itself (the function using `_split_into_sentence_groups`/`_build_sentence` and finalizing `end_page`) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_body_segmenter.py -v`
Expected: PASS — all 16 tests (10 pre-existing + 6 new), confirming the classification/end_page logic is untouched and content capture is correct.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/body_segmenter.py tests/test_body_segmenter.py
git commit -m "fix(mo_toc): capture full wrapped content for Sentence/Clause/Subclause"
```

---

### Task 4: `image_matcher.py` — deeper ownership + `title` formatting

**Files:**
- Modify: `src/mo_toc/parsing/image_matcher.py`
- Test: `tests/test_image_matcher.py`

**Interfaces:**
- Consumes: `ImageAsset.title` (Task 1).
- Produces: `match_images(...)` now descends ownership into Sentence/Clause/Subclause (removed from the exclusion set) and never into Table/Row/Cell (added to it); sets `ImageAsset.title = f"{kind} {identifier}"` when a caption is matched, else `""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_image_matcher.py`:

```python
def test_image_owner_descends_into_sentence_when_positioned_after_it():
    sentence = _node("Sentence", "(1)", "A-1.1.1.1.(1)", page=10, end_page=10)
    sentence.bbox = BBox(0, 100, 0, 0)
    article = _node("Article", "1.1.1.1.", "A-1.1.1.1.", page=10, end_page=12, children=[sentence])
    part = _node("Part", "1", "A-1", page=7, end_page=20, children=[article])
    division = _node("Division", "A", "A", page=6, end_page=30, children=[part])
    volume = _node("Volume", "Volume", "Volume", page=1, end_page=30, children=[division])

    image = _image(page=10, y0=150, y1=200)
    result = match_images([image], [], volume)
    assert result[0].owner_citation == "A-1.1.1.1.(1)"


def test_image_owner_descends_into_clause_when_positioned_after_it():
    clause = _node("Clause", "(a)", "A-1.1.1.1.(1)(a)", page=10, end_page=10)
    clause.bbox = BBox(0, 200, 0, 0)
    sentence = _node("Sentence", "(1)", "A-1.1.1.1.(1)", page=10, end_page=10, children=[clause])
    sentence.bbox = BBox(0, 100, 0, 0)
    article = _node("Article", "1.1.1.1.", "A-1.1.1.1.", page=10, end_page=12, children=[sentence])
    part = _node("Part", "1", "A-1", page=7, end_page=20, children=[article])
    division = _node("Division", "A", "A", page=6, end_page=30, children=[part])
    volume = _node("Volume", "Volume", "Volume", page=1, end_page=30, children=[division])

    formula_image = _image(page=10, y0=210, y1=225, x0=100, x1=140)  # small inline formula
    result = match_images([formula_image], [], volume)
    assert result[0].owner_citation == "A-1.1.1.1.(1)(a)"


def test_image_owner_never_descends_into_table_row_or_cell():
    cell = _node("Cell", "Col1", "Table:1.1.(1)-Row1-Col1", page=8, end_page=8)
    cell.bbox = BBox(0, 300, 0, 0)
    row = _node("Row", "Row1", "Table:1.1.(1)-Row1", page=8, end_page=8, children=[cell])
    row.bbox = BBox(0, 250, 0, 0)
    table = _node("Table", "1.1.(1)", "Table:1.1.(1)", page=8, end_page=8, children=[row])
    table.bbox = BBox(0, 200, 0, 0)
    article = _node("Article", "1.1.1.1.", "A-1.1.1.1.", page=8, end_page=9, children=[table])
    part = _node("Part", "1", "A-1", page=7, end_page=20, children=[article])
    division = _node("Division", "A", "A", page=6, end_page=30, children=[part])
    volume = _node("Volume", "Volume", "Volume", page=1, end_page=30, children=[division])

    image = _image(page=8, y0=350, y1=400)
    result = match_images([image], [], volume)
    assert result[0].owner_citation == "A-1.1.1.1."


def test_image_title_combines_caption_kind_and_identifier_when_matched():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    caption = _caption("Figure", "A-1.1.1.1.(6)", page=11, y0=155, y1=170)
    result = match_images([image], [caption], volume)
    assert result[0].title == "Figure A-1.1.1.1.(6)"


def test_image_title_is_empty_when_no_caption_matched():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    result = match_images([image], [], volume)
    assert result[0].title == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_image_matcher.py -v`
Expected: FAIL — the descent tests fail because `Sentence`/`Clause` are still in `_NON_OWNER_TYPES` (owner resolves to `A-1.1.1.1.` instead of the Sentence/Clause citation); the title tests fail because `ImageAsset.title` is never set by `match_images`.

- [ ] **Step 3: Implement**

In `src/mo_toc/parsing/image_matcher.py`, change the exclusion set and add title formatting:

```python
# Table/Row/Cell are never pushed as position-walkable owners - an image is
# never attributed to a specific table cell, matching how images are never
# themselves parsed as table content. Sentence/Clause/Subclause, by
# contrast, ARE valid owners now that body_segmenter gives them accurate
# per-node bboxes - an inline formula image inside a single Clause resolves
# to that Clause, not the enclosing Article.
_NON_OWNER_TYPES = {"Table", "Row", "Cell"}
```

And in `match_images`, add the `title` field to the `dataclasses.replace(...)` call:

```python
def match_images(
    images: list[ImageAsset], captions: list[Caption], volume: Node
) -> list[ImageAsset]:
    claimed_ids = set()
    enriched = []
    for image in images:
        owner_citation = assign_owner(image, volume)
        caption = _claim_caption(image, captions, claimed_ids)
        title = f"{caption.kind} {caption.identifier}" if caption else ""
        enriched.append(
            dataclasses.replace(
                image,
                owner_citation=owner_citation,
                caption_kind=caption.kind if caption else None,
                caption_identifier=caption.identifier if caption else None,
                caption_title=caption.title if caption else None,
                title=title,
            )
        )
    return enriched
```

Also update the module docstring's comment above `_NON_OWNER_TYPES` (currently describing the old Sentence/Clause/Subclause exclusion) — replace it with the comment shown above, and delete the now-stale reference to "Sentence/Clause/Subclause are never pushed onto tree_builder's own open-node stack" reasoning from the module-level docstring if it duplicates this.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_image_matcher.py -v`
Expected: PASS — all pre-existing tests (which only ever positioned images at Article/Note/Division granularity) plus the 5 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/image_matcher.py tests/test_image_matcher.py
git commit -m "feat(mo_toc): let image ownership descend into Sentence/Clause/Subclause"
```

---

### Task 5: `table_extractor.py` part 1 — grid detection and Table/Row/Cell construction

**Files:**
- Create: `src/mo_toc/parsing/table_extractor.py`
- Test: `tests/test_table_extractor.py`

**Interfaces:**
- Consumes: `PageLine` (`mo_toc.parsing.pdf_source`), `classify_caption_line`/`is_caption_font` (`mo_toc.parsing.heading_rules`), `Node`/`BBox` (`mo_toc.domain.models`).
- Produces:
  - `TableAnchor` dataclass: `page_index: int`, `caption_line_idx: int`, `identifier: str`.
  - `TableRegion` dataclass: `anchor: TableAnchor`, `table_node: Node`, `forming_part_of: tuple[str, str] | None`, `consumed_line_indices: set[int]`, `has_bottom_border: bool`, `outer_bbox: BBox`.
  - `find_table_anchors(lines: list[PageLine], page_index: int) -> list[TableAnchor]`
  - `detect_tables_on_page(lines: list[PageLine], drawing_rects: list[tuple[float,float,float,float]], page_number: int) -> list[TableRegion]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_extractor.py`:

```python
from mo_toc.parsing.pdf_source import PageLine
from mo_toc.parsing.table_extractor import detect_tables_on_page, find_table_anchors

CAPTION_FONT = "Arial-BoldMT"
BODY_FONT = "ArialMT"


def pline(x0, y0, x1, y1, text, font=BODY_FONT):
    return PageLine(bbox=(x0, y0, x1, y1), text=text, font=font)


def _minimal_grid_fixture():
    lines = [
        pline(200, 10, 300, 20, "Table 1.1.(1)", CAPTION_FONT),
        pline(150, 22, 350, 32, "Sample Title", CAPTION_FONT),
        pline(90, 50, 110, 60, "No.", CAPTION_FONT),
        pline(120, 50, 250, 60, "Description", CAPTION_FONT),
        pline(90, 70, 110, 80, "1", BODY_FONT),
        pline(120, 70, 250, 80, "First row content.", BODY_FONT),
    ]
    rects = [
        (90.0, 45.0, 260.0, 45.4),    # top border
        (90.0, 45.0, 90.4, 90.0),     # left border
        (259.6, 45.0, 260.0, 90.0),   # right border
        (90.0, 65.0, 260.0, 65.4),    # header/body divider
        (90.0, 89.6, 260.0, 90.0),    # bottom border
        (114.6, 45.0, 115.0, 90.0),   # column divider
    ]
    return lines, rects


def test_find_table_anchors_finds_identifier():
    lines, _ = _minimal_grid_fixture()
    anchors = find_table_anchors(lines, page_index=6)
    assert len(anchors) == 1
    assert anchors[0].identifier == "1.1.(1)"
    assert anchors[0].caption_line_idx == 0


def test_find_table_anchors_ignores_figure_captions():
    lines = [pline(200, 10, 300, 20, "Figure 1.1.(1)", CAPTION_FONT)]
    assert find_table_anchors(lines, page_index=6) == []


def test_detect_tables_on_page_builds_header_and_data_row():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    assert len(regions) == 1
    table = regions[0].table_node
    assert table.type == "Table"
    assert table.citation == "Table:1.1.(1)"
    assert table.page == 7
    header, data = table.children
    assert header.type == "Row"
    assert [c.content for c in header.children] == ["No.", "Description"]
    assert [c.content for c in data.children] == ["1", "First row content."]


def test_detect_tables_on_page_assigns_citations_by_position():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    header, data = regions[0].table_node.children
    assert header.citation == "Table:1.1.(1)-Row1"
    assert data.citation == "Table:1.1.(1)-Row2"
    assert data.children[0].citation == "Table:1.1.(1)-Row2-Col1"
    assert data.children[1].citation == "Table:1.1.(1)-Row2-Col2"


def test_detect_tables_on_page_marks_consumed_line_indices():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    # caption trigger (0) + the 4 cell-content lines (2,3,4,5); the
    # descriptive title line (1) is already excluded by tree_builder's
    # existing caption-title consumption, not by table_extractor.
    assert regions[0].consumed_line_indices == {0, 2, 3, 4, 5}


def test_detect_tables_on_page_returns_nothing_below_minimum_grid_size():
    lines = [
        pline(200, 10, 300, 20, "Table 1.1.(1)", CAPTION_FONT),
        pline(90, 50, 110, 60, "Only one column, no real grid.", BODY_FONT),
    ]
    rects = [(90.0, 45.0, 260.0, 45.4)]  # a single thin rule line, not a grid
    assert detect_tables_on_page(lines, rects, page_number=7) == []


def test_detect_tables_on_page_captures_forming_part_of_line():
    lines, rects = _minimal_grid_fixture()
    lines.insert(2, pline(150, 34, 350, 44, "Forming part of Sentence 1.1.1.1.(1)", BODY_FONT))
    regions = detect_tables_on_page(lines, rects, page_number=7)
    assert regions[0].forming_part_of == ("Sentence", "1.1.1.1.(1)")
    assert 2 in regions[0].consumed_line_indices


def test_detect_tables_on_page_forming_part_of_absent_when_no_match():
    lines, rects = _minimal_grid_fixture()
    regions = detect_tables_on_page(lines, rects, page_number=7)
    assert regions[0].forming_part_of is None


def test_cell_content_joins_multiple_physical_lines_in_one_cell():
    lines, rects = _minimal_grid_fixture()
    lines.append(pline(120, 82, 250, 88, "continues wrapping.", BODY_FONT))
    rects[4] = (90.0, 92.0, 260.0, 92.4)  # push the bottom border down to fit the extra line
    rects[1] = (90.0, 45.0, 90.4, 92.0)
    rects[2] = (259.6, 45.0, 260.0, 92.0)
    rects[5] = (114.6, 45.0, 115.0, 92.0)
    regions = detect_tables_on_page(lines, rects, page_number=7)
    data_row = regions[0].table_node.children[1]
    assert data_row.children[1].content == "First row content. continues wrapping."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_table_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mo_toc.parsing.table_extractor'`.

- [ ] **Step 3: Implement `table_extractor.py`**

Create `src/mo_toc/parsing/table_extractor.py`:

```python
"""Detects tables from a Table-kind caption anchor plus the page's own
vector-drawn gridlines (PdfSource.page_drawing_rects), building a
Table -> Row -> Cell subtree per detected grid, one page at a time.

Anchored, not blind: rather than scanning every page for grid-shaped rects
(risking false positives on ordinary boxes/borders), detection starts from
a Table caption line, already reliably found via classify_caption_line.
Multi-page stitching and owner attachment are a separate pass (see
stitch_continuations/attach_tables) since they need the full tree.
"""

import re
from dataclasses import dataclass

from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.heading_rules import classify_caption_line
from mo_toc.parsing.pdf_source import PageLine

RE_FORMING_PART_OF = re.compile(
    r"^Forming [Pp]art of (Sentence|Clause|Subclause|Article|Section|Subsection)\s+(.+?)\.?$"
)

LINE_THICKNESS_MAX = 2.0  # pt; a gridline rect's thin dimension
BOUNDARY_MERGE_TOLERANCE = 2.0  # pt; nearby edges from adjacent segments are one boundary
MIN_TABLE_ROWS = 2  # header + at least one data row
MIN_TABLE_COLS = 2


@dataclass
class TableAnchor:
    page_index: int
    caption_line_idx: int
    identifier: str


@dataclass
class TableRegion:
    anchor: TableAnchor
    table_node: Node
    forming_part_of: tuple[str, str] | None
    consumed_line_indices: set[int]
    has_bottom_border: bool
    outer_bbox: BBox


def find_table_anchors(lines: list[PageLine], page_index: int) -> list[TableAnchor]:
    anchors = []
    for idx, pline in enumerate(lines):
        cap_match = classify_caption_line(pline.text, pline.font)
        if cap_match and cap_match.group(1) == "Table":
            anchors.append(
                TableAnchor(
                    page_index=page_index,
                    caption_line_idx=idx,
                    identifier=cap_match.group(2).strip(),
                )
            )
    return anchors


def _classify_rect(rect: tuple[float, float, float, float]) -> str | None:
    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    if width > height and height <= LINE_THICKNESS_MAX and width > LINE_THICKNESS_MAX:
        return "horizontal"
    if height > width and width <= LINE_THICKNESS_MAX and height > LINE_THICKNESS_MAX:
        return "vertical"
    return None


def _merge_boundaries(values: list[float]) -> list[float]:
    merged = []
    for v in sorted(values):
        if merged and v - merged[-1] <= BOUNDARY_MERGE_TOLERANCE:
            continue
        merged.append(v)
    return merged


def _grid_boundaries(
    rects: list[tuple[float, float, float, float]], below_y: float
) -> tuple[list[float], list[float]]:
    row_ys, col_xs = [], []
    for rect in rects:
        x0, y0, x1, y1 = rect
        if y0 < below_y - BOUNDARY_MERGE_TOLERANCE:
            continue
        kind = _classify_rect(rect)
        if kind == "horizontal":
            row_ys.append((y0 + y1) / 2)
        elif kind == "vertical":
            col_xs.append((x0 + x1) / 2)
    return _merge_boundaries(row_ys), _merge_boundaries(col_xs)


def _band_index(value: float, boundaries: list[float]) -> int | None:
    for i in range(len(boundaries) - 1):
        if boundaries[i] - BOUNDARY_MERGE_TOLERANCE <= value < boundaries[i + 1]:
            return i
    return None


def _assign_lines_to_cells(
    lines: list[PageLine], row_ys: list[float], col_xs: list[float]
) -> tuple[dict[tuple[int, int], list[PageLine]], set[int]]:
    cells: dict[tuple[int, int], list[PageLine]] = {}
    consumed = set()
    outer = (col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    for i, pline in enumerate(lines):
        cx = (pline.bbox[0] + pline.bbox[2]) / 2
        cy = (pline.bbox[1] + pline.bbox[3]) / 2
        if not (outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]):
            continue
        row_i, col_i = _band_index(cy, row_ys), _band_index(cx, col_xs)
        if row_i is None or col_i is None:
            continue
        cells.setdefault((row_i, col_i), []).append(pline)
        consumed.add(i)
    return cells, consumed


def _union_bbox(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _cell_bbox(in_cell: list[PageLine], fallback: BBox) -> BBox:
    if not in_cell:
        return fallback
    bbox = BBox(*in_cell[0].bbox)
    for pline in in_cell[1:]:
        bbox = _union_bbox(bbox, BBox(*pline.bbox))
    return bbox


def _cell_node(row_citation: str, col_i: int, in_cell: list[PageLine], fallback: BBox, page: int) -> Node:
    ordered = sorted(in_cell, key=lambda ln: ln.bbox[1])
    content = " ".join(ln.text for ln in ordered).strip()
    return Node(
        type="Cell", identifier=f"Col{col_i + 1}", citation=f"{row_citation}-Col{col_i + 1}",
        title="", content=content, page=page, end_page=page, bbox=_cell_bbox(in_cell, fallback),
    )


def _row_node(table_citation: str, row_i: int, page: int, cells: list[Node]) -> Node:
    bbox = cells[0].bbox
    for cell in cells[1:]:
        bbox = _union_bbox(bbox, cell.bbox)
    return Node(
        type="Row", identifier=f"Row{row_i + 1}", citation=f"{table_citation}-Row{row_i + 1}",
        title="", page=page, end_page=page, bbox=bbox, children=cells,
    )


def _forming_part_of_above(lines: list[PageLine], caption_idx: int, grid_top_y: float):
    for i in range(caption_idx + 1, len(lines)):
        pline = lines[i]
        if pline.bbox[1] >= grid_top_y:
            break
        match = RE_FORMING_PART_OF.match(pline.text)
        if match:
            return i, (match.group(1), match.group(2))
    return None, None


def _has_bottom_border(rects, row_bottom_y: float) -> bool:
    return any(
        _classify_rect(r) == "horizontal" and abs((r[1] + r[3]) / 2 - row_bottom_y) <= BOUNDARY_MERGE_TOLERANCE
        for r in rects
    )


def build_table_region(
    anchor: TableAnchor,
    lines: list[PageLine],
    drawing_rects: list[tuple[float, float, float, float]],
    page_number: int,
) -> TableRegion | None:
    caption_bottom = lines[anchor.caption_line_idx].bbox[3]
    row_ys, col_xs = _grid_boundaries(drawing_rects, below_y=caption_bottom)
    if len(row_ys) - 1 < MIN_TABLE_ROWS or len(col_xs) - 1 < MIN_TABLE_COLS:
        return None

    forming_idx, forming_part_of = _forming_part_of_above(lines, anchor.caption_line_idx, row_ys[0])
    cell_lines, consumed = _assign_lines_to_cells(lines, row_ys, col_xs)
    consumed.add(anchor.caption_line_idx)
    if forming_idx is not None:
        consumed.add(forming_idx)

    table_citation = f"Table:{anchor.identifier}"
    rows = []
    for row_i in range(len(row_ys) - 1):
        cells = []
        for col_i in range(len(col_xs) - 1):
            in_cell = cell_lines.get((row_i, col_i), [])
            fallback = BBox(col_xs[col_i], row_ys[row_i], col_xs[col_i + 1], row_ys[row_i + 1])
            row_citation = f"{table_citation}-Row{row_i + 1}"
            cells.append(_cell_node(row_citation, col_i, in_cell, fallback, page_number))
        rows.append(_row_node(table_citation, row_i, page_number, cells))

    outer_bbox = BBox(col_xs[0], row_ys[0], col_xs[-1], row_ys[-1])
    table_node = Node(
        type="Table", identifier=anchor.identifier, citation=table_citation, title="",
        page=page_number, end_page=page_number, bbox=outer_bbox, children=rows,
    )
    return TableRegion(
        anchor=anchor, table_node=table_node, forming_part_of=forming_part_of,
        consumed_line_indices=consumed, has_bottom_border=_has_bottom_border(drawing_rects, row_ys[-1]),
        outer_bbox=outer_bbox,
    )


def detect_tables_on_page(
    lines: list[PageLine], drawing_rects: list[tuple[float, float, float, float]], page_number: int
) -> list[TableRegion]:
    anchors = find_table_anchors(lines, page_number - 1)
    regions = []
    for anchor in anchors:
        region = build_table_region(anchor, lines, drawing_rects, page_number)
        if region is not None:
            regions.append(region)
    return regions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_table_extractor.py -v`
Expected: PASS — all 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/table_extractor.py tests/test_table_extractor.py
git commit -m "feat(mo_toc): detect table grids and build Table/Row/Cell subtrees"
```

---

### Task 6: `table_extractor.py` part 2 — multi-page stitching and owner attachment

**Files:**
- Modify: `src/mo_toc/parsing/table_extractor.py`
- Test: `tests/test_table_extractor.py`

**Interfaces:**
- Consumes: `TableRegion` (Task 5), `image_matcher.assign_owner` (Task 4 — must run after Task 4 so ownership descent is already generalized).
- Produces:
  - `stitch_continuations(regions_by_page: list[list[TableRegion]]) -> list[TableRegion]`
  - `attach_tables(volume: Node, regions: list[TableRegion]) -> None` (mutates `volume` in place, appending each `table_node` under its resolved owner).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_extractor.py`:

```python
from mo_toc.domain.models import BBox, Node
from mo_toc.parsing.table_extractor import attach_tables, stitch_continuations


def _table_region(identifier, page, rows, has_bottom_border, outer_bbox, forming_part_of=None):
    anchor = TableAnchor(page_index=page - 1, caption_line_idx=0, identifier=identifier)
    table_node = Node(
        type="Table", identifier=identifier, citation=f"Table:{identifier}", title="",
        page=page, end_page=page, bbox=outer_bbox, children=rows,
    )
    return TableRegion(
        anchor=anchor, table_node=table_node, forming_part_of=forming_part_of,
        consumed_line_indices=set(), has_bottom_border=has_bottom_border, outer_bbox=outer_bbox,
    )


def _row(identifier, cells):
    return Node(
        type="Row", identifier=identifier, citation=f"r-{identifier}", title="",
        page=1, end_page=1, bbox=BBox(0, 0, 0, 0), children=cells,
    )


def _cell(identifier, content):
    return Node(
        type="Cell", identifier=identifier, citation=f"c-{identifier}", title="",
        content=content, page=1, end_page=1, bbox=BBox(0, 0, 0, 0),
    )


def test_stitch_continuations_merges_open_table_across_pages():
    row1 = _row("Row1", [_cell("Col1", "a"), _cell("Col2", "b")])
    page1_region = _table_region(
        "1.1.(1)", page=8, rows=[row1], has_bottom_border=False, outer_bbox=BBox(90, 400, 500, 700)
    )
    row2 = _row("Row1", [_cell("Col1", "c"), _cell("Col2", "d")])
    page2_region = _table_region(
        "1.1.(1)", page=9, rows=[row2], has_bottom_border=True, outer_bbox=BBox(90, 40, 500, 200)
    )
    stitched = stitch_continuations([[page1_region], [page2_region]])
    assert len(stitched) == 1
    table = stitched[0].table_node
    assert len(table.children) == 2
    assert table.children[1].identifier == "Row2"
    assert table.children[1].children[0].citation == "Table:1.1.(1)-Row2-Col1"
    assert table.end_page == 9


def test_stitch_continuations_keeps_closed_table_separate_from_next_one():
    row1 = _row("Row1", [_cell("Col1", "a")])
    page1_region = _table_region(
        "1.1.(1)", page=8, rows=[row1], has_bottom_border=True, outer_bbox=BBox(90, 400, 500, 700)
    )
    row2 = _row("Row1", [_cell("Col1", "x")])
    page2_region = _table_region(
        "1.1.(2)", page=9, rows=[row2], has_bottom_border=True, outer_bbox=BBox(90, 40, 500, 200)
    )
    stitched = stitch_continuations([[page1_region], [page2_region]])
    assert len(stitched) == 2


def test_attach_tables_resolves_owner_by_identifier_matching_a_citation():
    sentence = Node(
        type="Sentence", identifier="(5)", citation="A-1.1.1.1.(5)", title="",
        content="Sentence text.", page=8, end_page=8, bbox=BBox(0, 100, 0, 0),
    )
    article = Node(
        type="Article", identifier="1.1.1.1.", citation="A-1.1.1.1.", title="Title",
        page=8, end_page=8, bbox=BBox(0, 0, 0, 0), children=[sentence],
    )
    division = Node(
        type="Division", identifier="A", citation="A", title="", page=6, end_page=30,
        bbox=BBox(0, 0, 0, 0), children=[article],
    )
    volume = Node(
        type="Volume", identifier="Volume", citation="Volume", title="", page=1, end_page=30,
        bbox=BBox(0, 0, 0, 0), children=[division],
    )
    region = _table_region(
        "1.1.1.1.(5)", page=8, rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True, outer_bbox=BBox(90, 200, 500, 300),
    )
    attach_tables(volume, [region])
    assert len(sentence.children) == 1
    assert sentence.children[0].citation == "Table:1.1.1.1.(5)"


def test_attach_tables_falls_back_to_forming_part_of_line():
    sentence = Node(
        type="Sentence", identifier="(5)", citation="A-1.1.1.1.(5)", title="",
        content="Sentence text.", page=8, end_page=8, bbox=BBox(0, 100, 0, 0),
    )
    article = Node(
        type="Article", identifier="1.1.1.1.", citation="A-1.1.1.1.", title="Title",
        page=8, end_page=8, bbox=BBox(0, 0, 0, 0), children=[sentence],
    )
    division = Node(
        type="Division", identifier="A", citation="A", title="", page=6, end_page=30,
        bbox=BBox(0, 0, 0, 0), children=[article],
    )
    volume = Node(
        type="Volume", identifier="Volume", citation="Volume", title="", page=1, end_page=30,
        bbox=BBox(0, 0, 0, 0), children=[division],
    )
    # identifier "1.1.(9)-A" doesn't match any citation directly - only the
    # "Forming part of Sentence 1.1.1.1.(5)" line resolves the true owner.
    region = _table_region(
        "1.1.(9)-A", page=8, rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True, outer_bbox=BBox(90, 200, 500, 300),
        forming_part_of=("Sentence", "1.1.1.1.(5)"),
    )
    attach_tables(volume, [region])
    assert len(sentence.children) == 1


def test_attach_tables_falls_back_to_position_when_neither_resolves():
    article = Node(
        type="Article", identifier="1.1.1.1.", citation="A-1.1.1.1.", title="Title",
        page=8, end_page=8, bbox=BBox(0, 0, 0, 0),
    )
    division = Node(
        type="Division", identifier="A", citation="A", title="", page=6, end_page=30,
        bbox=BBox(0, 0, 0, 0), children=[article],
    )
    volume = Node(
        type="Volume", identifier="Volume", citation="Volume", title="", page=1, end_page=30,
        bbox=BBox(0, 0, 0, 0), children=[division],
    )
    region = _table_region(
        "unresolvable-id", page=8, rows=[_row("Row1", [_cell("Col1", "x")])],
        has_bottom_border=True, outer_bbox=BBox(90, 200, 500, 300),
    )
    attach_tables(volume, [region])
    assert len(article.children) == 1
    assert article.children[0].citation == "Table:unresolvable-id"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_table_extractor.py -v`
Expected: FAIL — `ImportError: cannot import name 'attach_tables'` (and `stitch_continuations`).

- [ ] **Step 3: Implement stitching and attachment**

Append to `src/mo_toc/parsing/table_extractor.py`:

```python
from mo_toc.parsing.image_matcher import assign_owner


def _renumber_row(table_citation: str, row: Node, row_i: int) -> None:
    row.identifier = f"Row{row_i + 1}"
    row.citation = f"{table_citation}-{row.identifier}"
    for cell in row.children:
        cell.citation = f"{row.citation}-{cell.identifier}"


def _continues_previous(prev: TableRegion, next_region: TableRegion) -> bool:
    prev_cols = len(prev.table_node.children[0].children) if prev.table_node.children else 0
    next_cols = len(next_region.table_node.children[0].children) if next_region.table_node.children else 0
    same_x_range = (
        abs(prev.outer_bbox.x0 - next_region.outer_bbox.x0) <= BOUNDARY_MERGE_TOLERANCE
        and abs(prev.outer_bbox.x1 - next_region.outer_bbox.x1) <= BOUNDARY_MERGE_TOLERANCE
    )
    return not prev.has_bottom_border and prev_cols == next_cols and same_x_range


def _merge_into(pending: TableRegion, region: TableRegion) -> None:
    table_citation = pending.table_node.citation
    start = len(pending.table_node.children)
    for i, row in enumerate(region.table_node.children):
        _renumber_row(table_citation, row, start + i)
    pending.table_node.children.extend(region.table_node.children)
    pending.table_node.end_page = region.table_node.page
    pending.has_bottom_border = region.has_bottom_border


def stitch_continuations(regions_by_page: list[list[TableRegion]]) -> list[TableRegion]:
    stitched: list[TableRegion] = []
    pending: TableRegion | None = None
    for page_regions in regions_by_page:
        for region in page_regions:
            if pending is not None and _continues_previous(pending, region):
                _merge_into(pending, region)
                continue
            if pending is not None:
                stitched.append(pending)
            pending = region
    if pending is not None:
        stitched.append(pending)
    return stitched


def _citation_index(volume: Node) -> dict[str, Node]:
    index = {}

    def walk(node: Node) -> None:
        index[node.citation] = node
        for child in node.children:
            walk(child)

    walk(volume)
    return index


def _division_for_page(volume: Node, page: int) -> str:
    divisions = [c for c in volume.children if c.type == "Division"]
    candidates = [d for d in divisions if d.page <= page]
    chosen = max(candidates, key=lambda d: d.page) if candidates else (divisions[0] if divisions else None)
    return chosen.identifier if chosen else ""


def resolve_owner_citation(region: TableRegion, division: str, index: dict[str, Node], volume: Node) -> str:
    direct = index.get(f"{division}-{region.anchor.identifier}")
    if direct is not None:
        return direct.citation
    if region.forming_part_of is not None:
        _, ref = region.forming_part_of
        by_ref = index.get(f"{division}-{ref}") or index.get(ref)
        if by_ref is not None:
            return by_ref.citation
    return assign_owner(region.table_node, volume)


def attach_tables(volume: Node, regions: list[TableRegion]) -> None:
    index = _citation_index(volume)
    for region in regions:
        division = _division_for_page(volume, region.table_node.page)
        owner_citation = resolve_owner_citation(region, division, index, volume)
        owner = index[owner_citation]
        owner.children.append(region.table_node)
        index[region.table_node.citation] = region.table_node
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_table_extractor.py -v`
Expected: PASS — all 14 tests in the file.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/table_extractor.py tests/test_table_extractor.py
git commit -m "feat(mo_toc): stitch multi-page tables and attach them to their owner node"
```

---

### Task 7: `tree_builder.py` — skip table-consumed lines during the body walk

**Files:**
- Modify: `src/mo_toc/parsing/tree_builder.py`
- Test: `tests/test_tree_builder.py`

**Interfaces:**
- Consumes: nothing new from other tasks (takes a plain `dict[int, set[int]]`, decoupled from `table_extractor.py`'s types).
- Produces: `build_tree_from_lines(all_lines, page_count, consumed_by_page: dict[int, set[int]] | None = None) -> tuple[Node, list[Caption]]` and `build_tree(source, consumed_by_page=None)` — lines whose index is in `consumed_by_page[page_index]` are skipped entirely (never reach `_append_to_current_article`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tree_builder.py`:

```python
def test_consumed_line_indices_are_excluded_from_article_body():
    pages = [
        [
            line(50, 40, "Part 1", BLACK),
            line(70, 40, "Compliance", BLACK),
            line(90, 40, "Section  1.1.   General", BLACK),
            line(110, 40, "1.1.1. Application", BLACK),
            line(130, 40, "1.1.1.1. Application of this Code", BLACK),
            line(150, 40, "1) Real sentence text.", BODY),
            line(170, 40, "This line is inside a detected table.", BODY),
        ],
    ]
    without_skip, _ = build_tree_from_lines(pages, len(pages))
    with_skip, _ = build_tree_from_lines(pages, len(pages), consumed_by_page={0: {6}})

    article_without = without_skip.children[0].children[0].children[0].children[0]
    article_with = with_skip.children[0].children[0].children[0].children[0]

    # Without the skip-set, the stray line still gets swept into the
    # sentence's continuation content (the bug body_segmenter now fixes
    # would otherwise hide this, so this test also guards Task 3's fix).
    assert "detected table" in article_without.children[0].content
    assert "detected table" not in article_with.children[0].content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tree_builder.py -k consumed_line_indices -v`
Expected: FAIL — `TypeError: build_tree_from_lines() got an unexpected keyword argument 'consumed_by_page'`.

- [ ] **Step 3: Thread the skip-set through**

In `src/mo_toc/parsing/tree_builder.py`, modify `_process_page` to accept and check a `consumed` set:

```python
def _process_page(
    lines: list[PageLine], page_index: int, state: _BuildState, consumed: set[int]
) -> None:
    idx = 0
    while idx < len(lines):
        if idx in consumed:
            idx += 1
            continue
        pline = lines[idx]
        cap_match = classify_caption_line(pline.text, pline.font)
        if cap_match:
            idx = _open_caption(cap_match, page_index, lines, idx, state)
            continue
        heading = _classify_heading(pline, state)
        if heading:
            idx = _open_node(heading[0], heading[1], page_index, lines, idx, state)
            continue
        if _try_open_note(pline, page_index, state):
            idx += 1
            continue
        _append_to_current_article(pline, page_index, state)
        idx += 1
```

Modify `build_tree` and `build_tree_from_lines`:

```python
def build_tree(source: PdfSource, consumed_by_page: dict[int, set[int]] | None = None) -> tuple[Node, list[Caption]]:
    all_lines = [source.page_lines(i) for i in range(source.page_count)]
    return build_tree_from_lines(all_lines, source.page_count, consumed_by_page)


def build_tree_from_lines(
    all_lines: list[list[PageLine]], page_count: int, consumed_by_page: dict[int, set[int]] | None = None
) -> tuple[Node, list[Caption]]:
    """Same assembly as build_tree, but takes each page's lines pre-computed
    instead of pulling them from a live PdfSource - lets build_mo_toc.py
    extract every page's lines in parallel (the actual PyMuPDF work) and
    then run this stateful, inherently-sequential assembly step once, in the
    main process, over the results."""
    consumed_by_page = consumed_by_page or {}
    volume = Node(
        type="Volume", identifier="Volume", citation="Volume", title="",
        page=1, end_page=page_count, bbox=BBox(0, 0, 0, 0),
    )
    front_matter = Node(
        type="FrontMatter", identifier="FrontMatter", citation="FrontMatter", title="",
        page=1, end_page=1, bbox=BBox(0, 0, 0, 0),
    )
    volume.children.append(front_matter)
    state = _BuildState(stack=[(0, volume), (1, front_matter)])

    for page_index, lines in enumerate(all_lines):
        _process_page(lines, page_index, state, consumed_by_page.get(page_index, set()))

    _finalize_end_pages(volume, page_count)
    for article, body in state.article_bodies:
        article.children = segment_article_body(body, article.citation, article.end_page)
    return volume, state.captions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tree_builder.py -v`
Expected: PASS — the new test plus every pre-existing test (default `consumed_by_page=None` preserves current behavior exactly).

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/tree_builder.py tests/test_tree_builder.py
git commit -m "feat(mo_toc): let tree_builder skip table-consumed lines during the body walk"
```

---

### Task 8: `parallel_extraction.py` + `image_extractor.py` — detect tables per page, exclude them from vector images

**Files:**
- Modify: `src/mo_toc/parsing/image_extractor.py`
- Modify: `src/mo_toc/parsing/parallel_extraction.py`
- Test: `tests/test_image_extractor.py` (create if it doesn't exist — check with `ls tests/test_image_extractor.py` first; if absent, create fresh with just these two tests plus a minimal existing-behavior smoke test)

**Interfaces:**
- Consumes: `detect_tables_on_page` (Task 5).
- Produces: `vector_images_on_page(source, page_index, raster_bboxes, drawing_rects=None, table_bboxes=())` — excludes `table_bboxes` from clustered candidates the same way `raster_bboxes` already are. `extract_all_pages(...) -> tuple[list[list[PageLine]], list[RawImage], list[list[TableRegion]]]`.

- [ ] **Step 1: Write the failing tests**

First check for an existing test file:

```bash
ls tests/test_image_extractor.py 2>/dev/null || echo "does not exist"
```

If it exists, append the tests below to it (adjusting imports to match its existing style); if not, create it fresh:

```python
from unittest.mock import MagicMock

from mo_toc.parsing.image_extractor import vector_images_on_page
from mo_toc.parsing.pdf_source import ExtractedImage


def _fake_source(rendered_bbox_capture):
    source = MagicMock()

    def render_region(page_index, bbox):
        rendered_bbox_capture.append(bbox)
        return ExtractedImage(data=b"x", ext="png", width=1, height=1)

    source.render_region.side_effect = render_region
    return source


def test_vector_images_on_page_excludes_table_bboxes():
    # A vector cluster that exactly matches a detected table's outer bbox
    # must not be rendered as a "figure" - it's a table border, not an image.
    rects = [(90.0, 90.0, 90.5, 400.0), (90.0, 400.0, 500.0, 400.5)]  # forms a >400pt^2 cluster
    rendered = []
    source = _fake_source(rendered)
    table_bboxes = [(85.0, 85.0, 505.0, 405.0)]  # overlaps the cluster fully

    result = vector_images_on_page(source, 0, raster_bboxes=[], drawing_rects=rects, table_bboxes=table_bboxes)

    assert result == []
    assert rendered == []


def test_vector_images_on_page_still_renders_clusters_outside_table_bboxes():
    rects = [(90.0, 90.0, 90.5, 400.0), (90.0, 400.0, 500.0, 400.5)]
    rendered = []
    source = _fake_source(rendered)

    result = vector_images_on_page(source, 0, raster_bboxes=[], drawing_rects=rects, table_bboxes=[])

    assert len(result) == 1
    assert len(rendered) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_image_extractor.py -v`
Expected: FAIL — `TypeError: vector_images_on_page() got an unexpected keyword argument 'table_bboxes'`.

- [ ] **Step 3: Implement**

In `src/mo_toc/parsing/image_extractor.py`, change `vector_images_on_page`:

```python
def vector_images_on_page(
    source: PdfSource,
    page_index: int,
    raster_bboxes: list[tuple[float, float, float, float]],
    drawing_rects: list[tuple[float, float, float, float]] | None = None,
    table_bboxes: list[tuple[float, float, float, float]] = (),
) -> list[RawImage]:
    rects = drawing_rects if drawing_rects is not None else source.page_drawing_rects(page_index)
    clusters = cluster_drawing_rects(rects)
    clusters = exclude_overlapping_rects(clusters, list(raster_bboxes) + list(table_bboxes))
    images = []
    for bbox in clusters:
        extracted = source.render_region(page_index, bbox)
        images.append(_raw_image(page_index, bbox, extracted))
    return images
```

Also update `extract_images` to keep working unchanged (it doesn't pass `drawing_rects`/`table_bboxes`, so the new optional params default to the prior behavior — no code change needed there, but confirm by re-reading `vector_images_on_page`'s call inside `extract_images`).

In `src/mo_toc/parsing/parallel_extraction.py`, thread table detection through the worker:

```python
from mo_toc.parsing.image_extractor import RawImage, raster_images_on_page, vector_images_on_page
from mo_toc.parsing.pdf_source import PageLine, PyMuPdfSource
from mo_toc.parsing.table_extractor import TableRegion, detect_tables_on_page

_worker_source: PyMuPdfSource | None = None


def _init_worker(pdf_path: str) -> None:
    global _worker_source
    _worker_source = PyMuPdfSource(pdf_path)


def _extract_page(page_index: int) -> tuple[list[PageLine], list[RawImage], list[TableRegion]]:
    assert _worker_source is not None
    lines = _worker_source.page_lines(page_index)
    raster = raster_images_on_page(_worker_source, page_index)
    rects = _worker_source.page_drawing_rects(page_index)
    table_regions = detect_tables_on_page(lines, rects, page_number=page_index + 1)
    table_bboxes = [r.outer_bbox.as_tuple() for r in table_regions]
    vector = vector_images_on_page(
        _worker_source, page_index, [r.bbox for r in raster], rects, table_bboxes
    )
    return lines, raster + vector, table_regions


def extract_all_pages(
    pdf_path: str, max_workers: int | None = None
) -> tuple[list[list[PageLine]], list[RawImage], list[list[TableRegion]]]:
    page_count = PyMuPdfSource(pdf_path).page_count
    workers = max_workers or os.cpu_count() or 1
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(pdf_path,)
    ) as executor:
        results = list(executor.map(_extract_page, range(page_count)))
    all_lines = [lines for lines, _, _ in results]
    all_images = [image for _, images, _ in results for image in images]
    all_table_regions = [regions for _, _, regions in results]
    return all_lines, all_images, all_table_regions
```

(`import os` and `from concurrent.futures import ProcessPoolExecutor` stay as-is at the top of the file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_image_extractor.py -v`
Expected: PASS. Also run `pytest tests/ -k parallel_extraction -v` if a `tests/test_parallel_extraction.py` file exists, to confirm its existing tests (which construct `_extract_page`/`extract_all_pages` results) still pass with the new 3-tuple return shape — update any that unpack a 2-tuple to unpack 3, following this task's `_extract_page`/`extract_all_pages` signatures exactly.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/image_extractor.py src/mo_toc/parsing/parallel_extraction.py tests/test_image_extractor.py tests/test_parallel_extraction.py
git commit -m "fix(mo_toc): stop rendering table borders as figures; detect tables per-page"
```

---

### Task 9: `build_mo_toc.py` — orchestrate table attachment and rename output to `mo_pdf.json`

**Files:**
- Modify: `src/build_mo_toc.py`
- Test: `tests/test_build_mo_toc.py` (create if absent)

**Interfaces:**
- Consumes: `extract_all_pages` (Task 8, 3-tuple return), `build_tree_from_lines` (Task 7, `consumed_by_page` param), `stitch_continuations`/`attach_tables` (Task 6).
- Produces: `run(pdf_path, output_dir)` writes `<output_dir>/mo_pdf.json` (renamed from `mo_toc.json`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_build_mo_toc.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import patch

from build_mo_toc import run


def test_run_writes_mo_pdf_json_not_mo_toc_json(tmp_path):
    fake_lines = [[]]
    with (
        patch("build_mo_toc.extract_all_pages", return_value=(fake_lines, [], [[]])),
        patch("build_mo_toc.write_images", return_value=[]),
    ):
        run(pdf_path="unused.pdf", output_dir=str(tmp_path))

    assert (tmp_path / "mo_pdf.json").exists()
    assert not (tmp_path / "mo_toc.json").exists()
    payload = json.loads((tmp_path / "mo_pdf.json").read_text())
    assert payload["volume"]["type"] == "Volume"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_build_mo_toc.py -v`
Expected: FAIL — `FileNotFoundError` on `mo_pdf.json` (current code writes `mo_toc.json`), or a `TypeError` if `extract_all_pages`'s mocked 3-tuple doesn't match the current 2-tuple unpacking in `run`.

- [ ] **Step 3: Implement**

Replace `src/build_mo_toc.py`'s `run` function and its imports:

```python
#!/usr/bin/env python3
"""Parses MO Package BCBC MRK signed.pdf into output/mo_pdf.json
and every embedded raster and vector-drawn image under output/images/.

Usage:
    python3 src/build_mo_toc.py                # uses data/<default PDF>
    python3 src/build_mo_toc.py /path/to/other.pdf
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mo_toc.output.image_writer import write_images
from mo_toc.output.json_writer import write_json
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.numbering_config import (
    MO_TOC_IDENTIFIER_TYPES,
    MO_TOC_SUFFIX_TYPES,
    MO_TOC_TYPE_MARKERS,
)
from mo_toc.parsing.parallel_extraction import extract_all_pages
from mo_toc.parsing.table_extractor import attach_tables, stitch_continuations
from mo_toc.parsing.tree_builder import build_tree_from_lines
from shared.numbering import assign_unified_numbers

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def _consumed_by_page(table_regions_by_page: list[list]) -> dict[int, set[int]]:
    return {
        page_index: {i for region in regions for i in region.consumed_line_indices}
        for page_index, regions in enumerate(table_regions_by_page)
        if regions
    }


def run(pdf_path: str, output_dir: str) -> None:
    all_lines, raw_images, table_regions_by_page = extract_all_pages(pdf_path)
    volume, captions = build_tree_from_lines(
        all_lines, len(all_lines), consumed_by_page=_consumed_by_page(table_regions_by_page)
    )
    attach_tables(volume, stitch_continuations(table_regions_by_page))
    assign_unified_numbers(
        [volume],
        MO_TOC_TYPE_MARKERS,
        identifier_types=MO_TOC_IDENTIFIER_TYPES,
        suffix_types=MO_TOC_SUFFIX_TYPES,
    )
    images = write_images(raw_images, str(Path(output_dir) / "images"))
    images = match_images(images, captions, volume)
    write_json(volume, captions, images, str(Path(output_dir) / "mo_pdf.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pdf_path", nargs="?", default=DEFAULT_PDF)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    if not Path(args.pdf_path).exists():
        sys.exit(f"No such file: {args.pdf_path}")
    print(f"Parsing {args.pdf_path} ...", file=sys.stderr)
    run(args.pdf_path, args.output_dir)
    print(f"Wrote {args.output_dir}/mo_pdf.json, images/", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_mo_toc.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/build_mo_toc.py tests/test_build_mo_toc.py
git commit -m "feat(mo_toc): attach tables during the build and rename output to mo_pdf.json"
```

---

### Task 10: `web/api.py` — read `mo_pdf.json`

**Files:**
- Modify: `src/mo_toc/web/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: nothing new (this only changes which file `serve_mo_toc.py`/callers point `create_app`'s `toc_json_path` at by convention — the function signature is unchanged, `toc_json_path` was already a parameter).

- [ ] **Step 1: Write the failing test**

Read `tests/test_api.py` first to see its existing fixture/import style, then add (adapting variable names to match):

```python
def test_create_app_works_with_a_file_literally_named_mo_pdf_json(tmp_path):
    toc_path = tmp_path / "mo_pdf.json"
    toc_path.write_text('{"volume": {"type": "Volume"}, "images": []}')
    app = create_app(toc_json_path=str(toc_path), pdf_path="unused.pdf", images_dir=str(tmp_path))
    client = TestClient(app)
    response = client.get("/api/toc")
    assert response.json()["type"] == "Volume"
```

(Use whatever test client fixture the file already uses — check the top of `tests/test_api.py` for an existing `TestClient`/`client` fixture pattern before adding this.)

- [ ] **Step 2: Run test to verify it fails or trivially passes**

Run: `pytest tests/test_api.py -v`

Since `create_app` already takes `toc_json_path` as a parameter (Task 10 doesn't change `api.py`'s code — `create_app` never hardcoded the filename), this test should already PASS. If so, skip to Step 5: this task is really about updating the **caller** that constructs the path, not `api.py` itself.

- [ ] **Step 3: Find and update the caller**

Search for where `create_app`'s `toc_json_path` argument is actually constructed:

```bash
grep -rn "mo_toc.json\|toc_json_path" src/mo_toc/web/ src/*.py
```

This will point to `src/serve_mo_toc.py` (or wherever `create_app(...)` is invoked with a literal `"mo_toc.json"` path). Update that literal to `"mo_pdf.json"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py tests/test_serve_mo_toc.py -v`
Expected: PASS. If `test_serve_mo_toc.py` has a fixture writing to a file literally named `output/mo_toc.json` or asserting on that filename, update it to `mo_pdf.json` to match — this is an update to an existing test's fixture path, not a behavior weakening, since the assertion it makes (the server correctly serves the TOC JSON) is unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/web/ src/serve_mo_toc.py tests/test_api.py tests/test_serve_mo_toc.py
git commit -m "chore(mo_toc): point the viewer server at mo_pdf.json"
```

---

### Task 11: `numbering_config.py` — Table/Row/Cell unified numbers

**Files:**
- Modify: `src/mo_toc/parsing/numbering_config.py`
- Test: `tests/test_mo_toc_numbering_config.py`

**Interfaces:**
- Produces: `MO_TOC_TYPE_MARKERS["Table"] = "Tbl"`; `MO_TOC_IDENTIFIER_TYPES` gains `"Row"` and `"Cell"` (so their own `Node.identifier`, e.g. `"Row1"`/`"Col1"`, is used directly as the dot-joined segment).

- [ ] **Step 1: Write the failing test**

Read `tests/test_mo_toc_numbering_config.py` first to match its existing style, then append:

```python
def test_table_row_cell_are_configured_for_numbering():
    assert MO_TOC_TYPE_MARKERS["Table"] == "Tbl"
    assert "Row" in MO_TOC_IDENTIFIER_TYPES
    assert "Cell" in MO_TOC_IDENTIFIER_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mo_toc_numbering_config.py -v`
Expected: FAIL — `KeyError: 'Table'`.

- [ ] **Step 3: Implement**

In `src/mo_toc/parsing/numbering_config.py`:

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
    "Table": "Tbl",
}

MO_TOC_IDENTIFIER_TYPES: frozenset[str] = frozenset({"Division", "Sentence", "Row", "Cell"})

MO_TOC_SUFFIX_TYPES: frozenset[str] = frozenset({"Clause", "Subclause"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mo_toc_numbering_config.py tests/test_mo_toc_numbering_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/numbering_config.py tests/test_mo_toc_numbering_config.py
git commit -m "feat(mo_toc): configure unified numbering for Table/Row/Cell"
```

---

### Task 12: `viewer.js` — render nodes whose label now comes from `content`

**Files:**
- Modify: `src/mo_toc/web/static/viewer.js`

**Interfaces:**
- Produces: `formatNodeLabel(node)` falls back to `node.content` when `node.title` is absent/undefined, so Sentence/Clause/Subclause/Cell tree rows show their text instead of `undefined`.

- [ ] **Step 1: Confirm the current implementation**

Read `src/mo_toc/web/static/viewer.js` around line 11-13 (the `formatNodeLabel` function) to confirm the exact current code before editing — it's `[node.unified_number, node.type, node.identifier, node.title].filter(Boolean).join(" ")` per prior investigation, but confirm since this task doesn't have an automated test (no JS test harness exists in this repo) and must not silently diverge from the real file.

- [ ] **Step 2: Edit `formatNodeLabel`**

Change:

```javascript
function formatNodeLabel(node) {
  return [node.unified_number, node.type, node.identifier, node.title].filter(Boolean).join(" ");
}
```

to:

```javascript
function formatNodeLabel(node) {
  const text = node.title || node.content;
  return [node.unified_number, node.type, node.identifier, text].filter(Boolean).join(" ");
}
```

- [ ] **Step 3: Manually verify in the browser**

Run: `python -m uvicorn app:app --reload` is for the *other* tool in this repo (Directory/Drive app) — for this viewer, run `python src/serve_mo_toc.py` (check its actual invocation in `CLAUDE.md`/the file itself) after regenerating `output/mo_pdf.json` via `python src/build_mo_toc.py` on a small page range if the script supports one, or accept the real full-PDF run from Task 13. Open the viewer, expand a Sentence/Clause node, and confirm its tree row shows real text instead of being blank.

- [ ] **Step 4: No automated test for this step**

This repo has no JS test harness; Step 3's manual browser check is the verification for this task, consistent with `CLAUDE.md`'s note that UI changes are verified by using the feature in a browser.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/web/static/viewer.js
git commit -m "fix(mo_toc/web): fall back to content when a tree node has no title"
```

---

### Task 13: Real-PDF integration test updates

**Files:**
- Modify: `tests/test_integration_real_pdf.py`

**Interfaces:**
- Consumes: the full pipeline end-to-end (`build_mo_toc.run` or its constituent calls, per however this file currently invokes the real PDF — read it first).

- [ ] **Step 1: Read the existing file**

Run: `cat tests/test_integration_real_pdf.py` (or use the Read tool) to see its current structure — how it invokes the pipeline, what markers/fixtures it uses, and what it currently asserts, before adding to it.

- [ ] **Step 2: Add assertions for the specific examples verified during design**

Add a new `@pytest.mark.slow` test (matching the file's existing style) asserting on the three concrete real-document facts established while designing this feature:

```python
@pytest.mark.slow
def test_clause_1_1_1_1_k_has_its_full_wrapped_text():
    # Confirmed bug this feature fixes: this clause's text used to cut off
    # mid-sentence at "...installation, replacement, or" because the second
    # physical line was silently dropped.
    volume, captions = _build_real_tree()  # reuse this file's existing helper for building the real tree
    node = _find_by_citation(volume, "A-1.1.1.1.(1)(k)")  # reuse/add a citation-lookup helper
    assert node.content == (
        "except as permitted by the British Columbia Fire Code, the installation, "
        "replacement, or alteration of materials or equipment regulated by this Code,"
    )
    assert node.title == ""


@pytest.mark.slow
def test_table_1_1_1_1_5_is_attached_as_a_sentence_child_with_rows_and_cells():
    volume, captions = _build_real_tree()
    sentence = _find_by_citation(volume, "A-1.1.1.1.(5)")
    tables = [c for c in sentence.children if c.type == "Table"]
    assert len(tables) == 1
    table = tables[0]
    assert table.title == "Alternate Compliance Methods for Heritage Buildings"
    first_row = table.children[0]
    assert [c.content for c in first_row.children] == [
        "No.", "Code Requirement in Division B", "Alternate Compliance Method",
    ]


@pytest.mark.slow
def test_figure_a_1_1_1_1_6_has_a_formatted_title_and_note_level_owner():
    from mo_toc.parsing.image_matcher import match_images

    volume, captions = _build_real_tree()
    images = ...  # build via this file's existing image-extraction helper, then:
    matched = match_images(images, captions, volume)
    figure = next(i for i in matched if i.caption_identifier == "A-1.1.1.1.(6)")
    assert figure.title == "Figure A-1.1.1.1.(6)"
    assert figure.owner_citation == "Note:A-1.1.1.1.(6)"
```

Adjust the helper names (`_build_real_tree`, `_find_by_citation`) to match whatever this file's existing helpers are actually called — do not invent new ones if equivalents already exist; add a small `_find_by_citation(node, citation)` recursive walk helper if the file doesn't already have one (mirrors the ad hoc lookup used throughout this design's own investigation).

- [ ] **Step 3: Run against the real PDF**

Run: `pytest tests/test_integration_real_pdf.py -m slow -v`
Expected: PASS. This is the first point in the plan where the full, real 1685-page PDF validates every earlier task's synthetic-fixture tests against the genuine document — if the grid-detection thresholds (`LINE_THICKNESS_MAX`, `BOUNDARY_MERGE_TOLERANCE`, `MIN_TABLE_ROWS`/`MIN_TABLE_COLS` in `table_extractor.py`) need tuning against real tables elsewhere in the document, do it here and re-run, rather than guessing thresholds up front.

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q` (fast suite) and `pytest -q -m slow` (real-PDF suite)
Expected: both fully green.

- [ ] **Step 5: Commit and run the definition-of-done checklist**

```bash
git add tests/test_integration_real_pdf.py
git commit -m "test(mo_toc): verify full-content/table/image extraction against the real PDF"
```

Then run, and fix anything reported, per `CLAUDE.md`'s Definition of Done (scoped to `src/mo_toc/`, `src/build_mo_toc.py`, `src/mo_toc/web/`, `src/shared/`, `tests/`):

```bash
ruff check --fix src/mo_toc src/build_mo_toc.py src/shared tests && ruff format src/mo_toc src/build_mo_toc.py src/shared tests
radon cc -s -n B src/mo_toc src/build_mo_toc.py src/shared
vulture src/mo_toc src/build_mo_toc.py src/shared
pytest --cov=src/mo_toc --cov=src/build_mo_toc --cov=src/shared
```

Commit any fixes as a final `chore(mo_toc): definition-of-done cleanup` commit if needed.

---

## Self-Review Notes

**Spec coverage:** Task 1 → schema additions. Task 2 → title/content pruning. Task 3 → Sentence/Clause/Subclause full-content fix. Task 4 → image ownership descent + title formatting. Tasks 5-6 → table detection, stitching, owner resolution (identifier match → Forming-part-of → position fallback). Task 7 → table-line exclusion from Article body. Task 8 → table-border-as-image fix. Task 9 → `mo_pdf.json` rename + orchestration. Task 10 → server path update. Task 11 → numbering. Task 12 → viewer fallback. Task 13 → real-PDF verification of the three concrete examples this design was grounded in. Every spec section has a task.

**Known follow-ups intentionally left out of this plan** (per the spec's "Out of scope" section): merged/spanning table cells, and any further disambiguation of image ownership beyond the existing nearest-preceding-sibling walk.
