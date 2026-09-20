# Unified Document-Level Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a purely positional `unified_number` (`volume.division.part.section.subsection.article.sentence.clause.subclause`) to every node of both the `mo_toc` (PDF) tree and the `web_toc` (website) tree, surfaced in both JSON outputs and in all three viewer tree tabs.

**Architecture:** A new dependency-free `src/shared/numbering.py` module implements the walk-and-count algorithm once; each package supplies its own type→marker table (`mo_toc/parsing/numbering_config.py`, `web_toc/parsing/numbering_config.py`) describing which of its node types are canonical document levels vs. which need a marker prefix. Each build script (`build_mo_toc.py`, `build_web_toc.py`) calls the shared function once, after building its tree and before writing output. `viewer.js` gets one small formatting helper used at the 4 places it already renders a node's label.

**Tech Stack:** Python 3 (dataclasses, no new dependencies), vanilla JS (viewer).

**Spec:** [ai_docs/2026-09-21-unified-numbering-design.md](../2026-09-21-unified-numbering-design.md)

## Global Constraints

- Numbering is computed independently per tree (`mo_toc`, `web_toc`) — no cross-tree number matching is required or guaranteed (the two trees are shaped differently: the website splits Part 9 - Housing into a second `volume`, the PDF does not).
- `unified_number` defaults to `""` and is appended as the **last** field on `Node` and `WebNode` (after `children`), so every existing positional and keyword construction call site keeps working unchanged.
- Segment format: a canonical-level type (maps to `None` in the marker table) gets a plain decimal position, no zero-padding (`"9"`, `"10"`); a marker type gets `f"{marker}{position}"` (e.g. `"App1"`); a type absent from the marker table entirely falls back to using its own type string as the marker.
- Position counters are scoped per node-type, per parent — siblings of a different type never share a counter.
- The final `unified_number` string never has a leading or trailing dot.
- Only `output/mo_toc.json`, `output/web_toc.json`, and `viewer.js` are updated to surface the field. `mo_toc.md` (markdown writer) and the flat Table/Figure caption/image indices are explicitly out of scope — do not touch `markdown_writer.py`, `Caption`, or `ImageAsset`/`WebImage`.
- `src/shared/numbering.py` must have zero imports from `mo_toc` or `web_toc` — it duck-types on any object exposing `.type`, `.children`, and a settable `.unified_number`.
- Never weaken or delete an existing test. Where wiring a new call breaks an existing mocked test (see Task 6), extend that test with a new mock/assertion rather than removing coverage.

---

### Task 1: Shared numbering algorithm

**Files:**
- Create: `src/shared/__init__.py`
- Create: `src/shared/numbering.py`
- Test: `tests/test_numbering.py`

**Interfaces:**
- Produces: `assign_unified_numbers(nodes: list, type_to_marker: dict[str, str | None], parent_number: str = "") -> None` — mutates `.unified_number` on every node in `nodes` and all descendants, in place. `nodes` is a list of top-level siblings to number (not a single root object).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_numbering.py`:

```python
from dataclasses import dataclass, field

from shared.numbering import assign_unified_numbers


@dataclass
class _StubNode:
    type: str
    children: list["_StubNode"] = field(default_factory=list)
    unified_number: str = ""


def test_assigns_plain_numbers_for_canonical_types():
    article = _StubNode(type="article")
    part = _StubNode(type="part", children=[article])
    volume = _StubNode(type="volume", children=[part])
    markers = {"volume": None, "part": None, "article": None}

    assign_unified_numbers([volume], markers)

    assert volume.unified_number == "1"
    assert part.unified_number == "1.1"
    assert article.unified_number == "1.1.1"


def test_counts_positions_per_type_not_globally():
    part_a = _StubNode(type="part")
    notes = _StubNode(type="notes")
    part_b = _StubNode(type="part")
    markers = {"part": None, "notes": "Notes"}

    assign_unified_numbers([part_a, notes, part_b], markers)

    assert part_a.unified_number == "1"
    assert notes.unified_number == "Notes1"
    assert part_b.unified_number == "2"


def test_marker_type_gets_prefixed_segment():
    appendix = _StubNode(type="appendix")
    part = _StubNode(type="part", children=[appendix])
    markers = {"part": None, "appendix": "App"}

    assign_unified_numbers([part], markers)

    assert appendix.unified_number == "1.App1"


def test_nested_marker_chain():
    appendix_part = _StubNode(type="appendix_part")
    appendix = _StubNode(type="appendix", children=[appendix_part])
    markers = {"appendix": "App", "appendix_part": "AppPt"}

    assign_unified_numbers([appendix], markers)

    assert appendix.unified_number == "App1"
    assert appendix_part.unified_number == "App1.AppPt1"


def test_unmapped_type_falls_back_to_type_name_as_marker():
    mystery = _StubNode(type="mystery")
    markers = {"part": None}

    assign_unified_numbers([mystery], markers)

    assert mystery.unified_number == "mystery1"


def test_leaf_node_with_no_children_does_not_crash():
    leaf = _StubNode(type="article", children=[])

    assign_unified_numbers([leaf], {"article": None})

    assert leaf.unified_number == "1"


def test_multiple_top_level_siblings_get_sequential_numbers():
    vol1 = _StubNode(type="volume")
    vol2 = _StubNode(type="volume")

    assign_unified_numbers([vol1, vol2], {"volume": None})

    assert vol1.unified_number == "1"
    assert vol2.unified_number == "2"


def test_parent_number_is_prefixed_when_given():
    child = _StubNode(type="section")

    assign_unified_numbers([child], {"section": None}, parent_number="9")

    assert child.unified_number == "9.1"


def test_position_above_nine_is_not_zero_padded():
    siblings = [_StubNode(type="article") for _ in range(10)]

    assign_unified_numbers(siblings, {"article": None})

    assert siblings[9].unified_number == "10"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_numbering.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'shared'` (the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `src/shared/__init__.py` (empty file).

Create `src/shared/numbering.py`:

```python
"""Assigns a dotted, purely positional unified_number to every node in a tree.

Duck-types on any object exposing `.type`, `.children`, and a settable
`.unified_number` — no dependency on any specific domain model.
"""


def assign_unified_numbers(
    nodes: list, type_to_marker: dict[str, str | None], parent_number: str = ""
) -> None:
    counters: dict[str, int] = {}
    for node in nodes:
        counters[node.type] = counters.get(node.type, 0) + 1
        node.unified_number = _number_for(node, counters[node.type], parent_number, type_to_marker)
        assign_unified_numbers(node.children, type_to_marker, node.unified_number)


def _number_for(node, position: int, parent_number: str, type_to_marker: dict[str, str | None]) -> str:
    is_canonical = node.type in type_to_marker and type_to_marker[node.type] is None
    marker = "" if is_canonical else type_to_marker.get(node.type, node.type)
    segment = str(position) if is_canonical else f"{marker}{position}"
    return f"{parent_number}.{segment}" if parent_number else segment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_numbering.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/shared/__init__.py src/shared/numbering.py tests/test_numbering.py
git commit -m "feat(shared): add unified_number assignment algorithm"
```

---

### Task 2: `mo_toc` domain model gains `unified_number`

**Files:**
- Modify: `src/mo_toc/domain/models.py`
- Test: `tests/test_domain_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Node.unified_number: str = ""` — a settable field later populated by `assign_unified_numbers` (Task 1) via Task 6's wiring.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_domain_models.py` (after `test_node_children_are_independent_between_instances`):

```python
def test_node_unified_number_defaults_to_empty_string():
    node = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=10,
        bbox=BBox(0, 0, 0, 0),
    )
    assert node.unified_number == ""


def test_node_unified_number_can_be_set():
    node = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="",
        page=7,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
        unified_number="1.1",
    )
    assert node.unified_number == "1.1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_domain_models.py -v`
Expected: FAIL — `TypeError: Node.__init__() got an unexpected keyword argument 'unified_number'` (and the defaults test fails with `AttributeError: 'Node' object has no attribute 'unified_number'`).

- [ ] **Step 3: Write the implementation**

In `src/mo_toc/domain/models.py`, modify the `Node` dataclass:

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_domain_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/domain/models.py tests/test_domain_models.py
git commit -m "feat(mo_toc): add unified_number field to Node"
```

---

### Task 3: `web_toc` domain model gains `unified_number`

**Files:**
- Modify: `src/web_toc/domain/models.py`
- Test: `tests/test_web_toc_domain_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `WebNode.unified_number: str = ""` — a settable field later populated by `assign_unified_numbers` (Task 1) via Task 7's wiring.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_toc_domain_models.py` (after `test_web_node_children_are_independent_between_instances`):

```python
def test_web_node_unified_number_defaults_to_empty_string():
    node = WebNode(
        type="section",
        identifier="1.1",
        citation="nbc.divA.part1.sect1",
        title="General",
        path="/code/nbc.divA/1/1",
    )
    assert node.unified_number == ""


def test_web_node_unified_number_can_be_set():
    node = WebNode(
        type="part",
        identifier="1",
        citation="nbc.divA.part1",
        title="",
        path="/code/nbc.divA/1",
        unified_number="1.1",
    )
    assert node.unified_number == "1.1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_toc_domain_models.py -v`
Expected: FAIL — `TypeError: WebNode.__init__() got an unexpected keyword argument 'unified_number'`.

- [ ] **Step 3: Write the implementation**

In `src/web_toc/domain/models.py`, modify the `WebNode` dataclass:

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_domain_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/domain/models.py tests/test_web_toc_domain_models.py
git commit -m "feat(web_toc): add unified_number field to WebNode"
```

---

### Task 4: `mo_toc` marker table

**Files:**
- Create: `src/mo_toc/parsing/numbering_config.py`
- Test: `tests/test_mo_toc_numbering_config.py`

**Interfaces:**
- Consumes: nothing (a plain data table).
- Produces: `MO_TOC_TYPE_MARKERS: dict[str, str | None]` — consumed by Task 6's wiring in `build_mo_toc.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mo_toc_numbering_config.py`:

```python
from mo_toc.parsing.numbering_config import MO_TOC_TYPE_MARKERS

CANONICAL_LEVELS = [
    "Volume",
    "Division",
    "Part",
    "Section",
    "Subsection",
    "Article",
    "Sentence",
    "Clause",
    "Subclause",
]

MARKER_TYPES = {
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


def test_canonical_document_levels_map_to_none():
    for level in CANONICAL_LEVELS:
        assert MO_TOC_TYPE_MARKERS[level] is None


def test_non_level_types_map_to_short_markers():
    for node_type, marker in MARKER_TYPES.items():
        assert MO_TOC_TYPE_MARKERS[node_type] == marker


def test_table_has_exactly_the_expected_keys():
    assert set(MO_TOC_TYPE_MARKERS) == set(CANONICAL_LEVELS) | set(MARKER_TYPES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mo_toc_numbering_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mo_toc.parsing.numbering_config'`.

- [ ] **Step 3: Write the implementation**

Create `src/mo_toc/parsing/numbering_config.py`:

```python
"""Maps mo_toc Node.type values to a unified-numbering marker: None for one of
the nine canonical document levels, or a short prefix for everything else."""

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mo_toc_numbering_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/parsing/numbering_config.py tests/test_mo_toc_numbering_config.py
git commit -m "feat(mo_toc): add unified-numbering marker table"
```

---

### Task 5: `web_toc` marker table

**Files:**
- Create: `src/web_toc/parsing/numbering_config.py`
- Test: `tests/test_web_toc_numbering_config.py`

**Interfaces:**
- Consumes: nothing (a plain data table).
- Produces: `WEB_TOC_TYPE_MARKERS: dict[str, str | None]` — consumed by Task 7's wiring in `build_web_toc.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_toc_numbering_config.py`:

```python
from web_toc.parsing.numbering_config import WEB_TOC_TYPE_MARKERS

CANONICAL_LEVELS = ["volume", "division", "part", "section", "subsection", "article"]

MARKER_TYPES = {
    "part_appendix": "App",
    "division_appendix": "App",
    "index": "Idx",
    "conversions": "Conv",
    "spectables": "Spec",
}


def test_canonical_document_levels_map_to_none():
    for level in CANONICAL_LEVELS:
        assert WEB_TOC_TYPE_MARKERS[level] is None


def test_non_level_types_map_to_short_markers():
    for node_type, marker in MARKER_TYPES.items():
        assert WEB_TOC_TYPE_MARKERS[node_type] == marker


def test_table_has_exactly_the_expected_keys():
    assert set(WEB_TOC_TYPE_MARKERS) == set(CANONICAL_LEVELS) | set(MARKER_TYPES)


def test_synthetic_root_type_is_not_in_the_table():
    assert "root" not in WEB_TOC_TYPE_MARKERS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_toc_numbering_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing.numbering_config'`.

- [ ] **Step 3: Write the implementation**

Create `src/web_toc/parsing/numbering_config.py`:

```python
"""Maps web_toc WebNode.type values to a unified-numbering marker: None for one
of the six canonical document levels this tree reaches, or a short prefix for
everything else. The synthetic "root" wrapper node is deliberately absent —
it is never passed to assign_unified_numbers (only its children are)."""

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_toc_numbering_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/numbering_config.py tests/test_web_toc_numbering_config.py
git commit -m "feat(web_toc): add unified-numbering marker table"
```

---

### Task 6: Wire numbering into `build_mo_toc.py`

**Files:**
- Modify: `src/build_mo_toc.py`
- Test: `tests/test_build_mo_toc.py`

**Interfaces:**
- Consumes: `assign_unified_numbers` (Task 1), `MO_TOC_TYPE_MARKERS` (Task 4).
- Produces: `run()`'s written `mo_toc.json` now contains populated `unified_number` fields (verified end-to-end in Task 8's manual check; this task verifies the wiring call itself).

- [ ] **Step 1: Write the failing test**

`tests/test_build_mo_toc.py`'s existing `test_run_wires_pipeline_in_order` mocks
`build_tree` to return a **plain string** `"VOLUME"` (not a real `Node`), to keep the
wiring test cheap. Once `run()` calls the real `assign_unified_numbers` on that string,
it will crash (`"VOLUME"` has no `.type`). So this task's "failing test" step is: add a
mock for the new call, and an assertion that it was called correctly. Replace the whole
test function (imports plus the one test) with:

```python
import sys
from unittest.mock import MagicMock, patch

import pytest

from build_mo_toc import main, run
from mo_toc.parsing.numbering_config import MO_TOC_TYPE_MARKERS


@patch("build_mo_toc.write_markdown")
@patch("build_mo_toc.write_json")
@patch("build_mo_toc.match_images")
@patch("build_mo_toc.write_thumbnails")
@patch("build_mo_toc.extract_images")
@patch("build_mo_toc.assign_unified_numbers")
@patch("build_mo_toc.build_tree")
@patch("build_mo_toc.PyMuPdfSource")
def test_run_wires_pipeline_in_order(
    mock_source_cls,
    mock_build_tree,
    mock_assign_numbers,
    mock_extract_images,
    mock_write_thumbs,
    mock_match_images,
    mock_write_json,
    mock_write_md,
    tmp_path,
):
    mock_source = MagicMock()
    mock_source_cls.return_value = mock_source
    mock_build_tree.return_value = ("VOLUME", ["CAPTION"])
    mock_extract_images.return_value = ["RAW_IMAGE"]
    mock_write_thumbs.return_value = ["IMAGE_ASSET"]
    mock_match_images.return_value = ["MATCHED_IMAGE_ASSET"]

    run("some.pdf", str(tmp_path))

    mock_source_cls.assert_called_once_with("some.pdf")
    mock_build_tree.assert_called_once_with(mock_source)
    mock_assign_numbers.assert_called_once_with(["VOLUME"], MO_TOC_TYPE_MARKERS)
    mock_extract_images.assert_called_once_with(mock_source)
    mock_write_thumbs.assert_called_once_with(["RAW_IMAGE"], str(tmp_path / "thumbnails"))
    mock_match_images.assert_called_once_with(["IMAGE_ASSET"], ["CAPTION"], "VOLUME")
    mock_write_json.assert_called_once_with(
        "VOLUME", ["CAPTION"], ["MATCHED_IMAGE_ASSET"], str(tmp_path / "mo_toc.json")
    )
    mock_write_md.assert_called_once_with("VOLUME", ["CAPTION"], str(tmp_path / "mo_toc.md"))


def test_main_exits_when_pdf_missing(tmp_path, monkeypatch):
    missing_pdf = str(tmp_path / "nope.pdf")
    monkeypatch.setattr(sys, "argv", ["build_mo_toc.py", missing_pdf])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert "No such file" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_build_mo_toc.py -v`
Expected: FAIL — `ImportError: cannot import name 'assign_unified_numbers' from 'build_mo_toc'` (nothing in `build_mo_toc.py` imports it yet, so `@patch("build_mo_toc.assign_unified_numbers")` cannot find the target).

- [ ] **Step 3: Write the implementation**

In `src/build_mo_toc.py`, update the import block to:

```python
from mo_toc.output.json_writer import write_json
from mo_toc.output.markdown_writer import write_markdown
from mo_toc.output.thumbnail_writer import write_thumbnails
from mo_toc.parsing.image_extractor import extract_images
from mo_toc.parsing.image_matcher import match_images
from mo_toc.parsing.numbering_config import MO_TOC_TYPE_MARKERS
from mo_toc.parsing.pdf_source import PyMuPdfSource
from mo_toc.parsing.tree_builder import build_tree
from shared.numbering import assign_unified_numbers
```

And update `run()` to:

```python
def run(pdf_path: str, output_dir: str) -> None:
    source = PyMuPdfSource(pdf_path)
    volume, captions = build_tree(source)
    assign_unified_numbers([volume], MO_TOC_TYPE_MARKERS)
    raw_images = extract_images(source)
    images = write_thumbnails(raw_images, str(Path(output_dir) / "thumbnails"))
    images = match_images(images, captions, volume)
    write_json(volume, captions, images, str(Path(output_dir) / "mo_toc.json"))
    write_markdown(volume, captions, str(Path(output_dir) / "mo_toc.md"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_mo_toc.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/build_mo_toc.py tests/test_build_mo_toc.py
git commit -m "feat(mo_toc): wire unified numbering into the build pipeline"
```

---

### Task 7: Wire numbering into `build_web_toc.py`

**Files:**
- Modify: `src/build_web_toc.py`
- Test: `tests/test_build_web_toc.py`

**Interfaces:**
- Consumes: `assign_unified_numbers` (Task 1), `WEB_TOC_TYPE_MARKERS` (Task 5).
- Produces: `run()`'s written `web_toc.json` now contains populated `unified_number` fields.

Unlike Task 6, the three existing tests in `test_build_web_toc.py` already build **real**
`WebNode` instances for `root`/`leaf` (not string mocks), so the real
`assign_unified_numbers` can run against them unmocked without crashing. This task adds
one assertion to the primary test proving the wiring actually ran, rather than needing a
new mock.

- [ ] **Step 1: Write the failing assertion**

In `tests/test_build_web_toc.py`, modify
`test_run_wires_pipeline_and_writes_images_from_every_content_bearing_node` by inserting
one line right after the `run(...)` call (before `mock_source_cls.assert_called_once_with`):

```python
    run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path))

    assert leaf.unified_number == "1"
    mock_source_cls.assert_called_once_with("https://dev.buildingcode.gov.bc.ca")
```

(Only that one `assert` line is new — everything else in the test file is unchanged.)

- [ ] **Step 2: Run tests to verify the new assertion fails**

Run: `pytest tests/test_build_web_toc.py -v`
Expected: FAIL on the new assertion — `AssertionError: assert '' == '1'` (`leaf.unified_number` is still its default `""`, since nothing sets it yet).

- [ ] **Step 3: Write the implementation**

In `src/build_web_toc.py`, update the import block to:

```python
from shared.numbering import assign_unified_numbers
from web_toc.output.json_writer import write_json
from web_toc.parsing.content_url import content_url
from web_toc.parsing.image_extractor import extract_images
from web_toc.parsing.numbering_config import WEB_TOC_TYPE_MARKERS
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.tree_builder import build_tree, collect_citations
```

And update `run()` to:

```python
def run(base_url: str, version: str, output_dir: str) -> None:
    source = HttpxWebSource(base_url, version)
    root = build_tree(source.fetch_navigation_tree())
    assign_unified_numbers(root.children, WEB_TOC_TYPE_MARKERS)
    citations = collect_citations(root)

    images = []
    for node in _walk(root):
        url = content_url(node, version)
        if url is None:
            continue
        print(f"Fetching {url} ...", file=sys.stderr)
        content = source.fetch_content(url)
        if content is None:
            print(f"  skipped (no content at {url})", file=sys.stderr)
            continue
        images.extend(extract_images(content, citations, node.citation))

    write_json(root, images, str(Path(output_dir) / "web_toc.json"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_web_toc.py -v`
Expected: PASS (all 3 tests in this file)

- [ ] **Step 5: Commit**

```bash
git add src/build_web_toc.py tests/test_build_web_toc.py
git commit -m "feat(web_toc): wire unified numbering into the build pipeline"
```

---

### Task 8: Display `unified_number` in the viewer

**Files:**
- Modify: `src/mo_toc/web/static/viewer.js`
- Modify: `src/mo_toc/web/static/index.html`

**Interfaces:**
- Consumes: the `unified_number` field now present on every node in `/api/toc` and
  `/api/web-toc` responses (Tasks 6 and 7).
- No automated JS test suite exists in this repo (confirmed — no JS test files under
  `tests/`); this task is verified by running the app and visually confirming, per this
  project's established practice for viewer/UI work.

- [ ] **Step 1: Add the shared label-formatting helper**

In `src/mo_toc/web/static/viewer.js`, insert this function right after the existing
`let allImages = null;` declaration and before `async function loadToc() {`:

```js
function formatNodeLabel(node) {
  return [node.unified_number, node.type, node.identifier, node.title].filter(Boolean).join(" ");
}
```

- [ ] **Step 2: Use it in `renderNode` (Table of Contents tab)**

Change:
```js
  row.textContent = `${hasChildren ? "▸ " : ""}${node.type} ${node.identifier} ${node.title}`.trim();
```
to:
```js
  row.textContent = `${hasChildren ? "▸ " : ""}${formatNodeLabel(node)}`.trim();
```

- [ ] **Step 3: Use it in `renderImageTreeNode` (Table of Images tab)**

Change:
```js
  row.textContent = `▸ ${node.type} ${node.identifier} ${node.title}`.trim();
```
(the one inside `renderImageTreeNode`) to:
```js
  row.textContent = `▸ ${formatNodeLabel(node)}`.trim();
```

- [ ] **Step 4: Use it in `renderWebTreeNode` (BC Code (Web) tab)**

Change:
```js
  row.textContent = `▸ ${node.type} ${node.identifier} ${node.title}`.trim();
```
(the one inside `renderWebTreeNode`) to:
```js
  row.textContent = `▸ ${formatNodeLabel(node)}`.trim();
```

- [ ] **Step 5: Use it in the web image detail panel**

Change:
```js
  document.getElementById("web-image-detail-citation").textContent =
    `${ownerNode.type} ${ownerNode.identifier} ${ownerNode.title}`.trim();
```
to:
```js
  document.getElementById("web-image-detail-citation").textContent = formatNodeLabel(ownerNode);
```

- [ ] **Step 6: Bump the cache-bust query param**

In `src/mo_toc/web/static/index.html`, change:
```html
  <script type="module" src="/static/viewer.js?v=4"></script>
```
to:
```html
  <script type="module" src="/static/viewer.js?v=5"></script>
```

- [ ] **Step 7: Verify by running the viewer**

```bash
python src/build_mo_toc.py
python src/build_web_toc.py
python src/serve_mo_toc.py
```
Open `http://localhost:8000`. Confirm:
- The **Table of Contents** tab shows a leading number (e.g. `1 Volume`, `1.2 Division`)
  before each row's type/identifier/title.
- The **Table of Images** tab shows the same numbers on its tree rows.
- The **BC Code (Web)** tab shows numbers on its tree rows, and clicking an image opens
  the detail panel with a numbered citation line.
- No existing behavior (expand/collapse, click-to-scroll, image thumbnails) regressed.

Stop the server (`Ctrl+C`) once confirmed.

- [ ] **Step 8: Commit**

```bash
git add src/mo_toc/web/static/viewer.js src/mo_toc/web/static/index.html
git commit -m "feat(viewer): display unified_number on tree rows"
```

---

### Task 9: Document the new field

**Files:**
- Modify: `Readme.md`
- Modify: `CLAUDE.md`

No tests — documentation only, verified by direct review (`git diff`) rather than a
subagent review, consistent with how the equivalent docs task was handled for the
`web_toc` feature.

- [ ] **Step 1: Add a new section to `Readme.md`**

Insert a new `## 4. Unified document-level numbering` section between the existing
`## 3. BC Building Code (Web) — Table of Images (`src/web_toc/`)` section and
`## Folder structure`:

```markdown
## 4. Unified document-level numbering

Both `mo_toc.json` and `web_toc.json` trees carry a `unified_number` on every node — a
purely positional `volume.division.part.section.subsection.article.sentence.clause.subclause`
label, computed independently within each tree (1-based position among same-type
siblings under the same parent). Node types outside those nine levels (front matter,
appendices, notes, index/conversion pages, etc.) still get a number, using a short type
marker plus their own position (e.g. `1.2.App1`). Because the PDF and website trees are
shaped slightly differently (the website splits Part 9 - Housing into a second volume,
the PDF does not), the same real section is not guaranteed to carry the same
`unified_number` in both tabs — it's a per-tree outline number, not a cross-reference
key. Shown in the viewer next to each tree row.
```

- [ ] **Step 2: Add a `shared/` bullet to `Readme.md`'s Folder structure list**

In the `- \`src/\` — Python modules and scripts.` bullet's sub-list, insert a new bullet
right after the existing `` `check_directory_access.py` `` bullet:

```markdown
  - `shared/` — small pure-function helpers with no dependency on either indexing
    library, shared between `mo_toc/` and `web_toc/` (currently just the unified
    document-level numbering algorithm).
```

- [ ] **Step 3: Update `CLAUDE.md`'s Folder structure section**

Insert a new bullet right after the existing `web_toc/` bullet:

```markdown
- `shared/` — small pure-function helpers with no dependency on either indexing
  library, shared between `mo_toc/` and `web_toc/` (currently just the unified
  document-level numbering algorithm used by both `build_mo_toc.py` and
  `build_web_toc.py`).
```

- [ ] **Step 4: Update `CLAUDE.md`'s Definition of done scope line**

Change:
```
`src/mo_toc/`, `src/build_mo_toc.py`, `src/serve_mo_toc.py`, `src/web_toc/`,
`src/build_web_toc.py`, and `tests/` — not the whole repo
```
to:
```
`src/mo_toc/`, `src/build_mo_toc.py`, `src/serve_mo_toc.py`, `src/web_toc/`,
`src/build_web_toc.py`, `src/shared/`, and `tests/` — not the whole repo
```

- [ ] **Step 5: Verify**

```bash
git diff Readme.md CLAUDE.md
```
Confirm only the intended additions appear — no other lines changed.

- [ ] **Step 6: Commit**

```bash
git add Readme.md CLAUDE.md
git commit -m "docs: document the unified document-level numbering feature"
```

---

## Final Verification

After Task 9, run the full scoped Definition of Done before handing off for review/PR:

```bash
ruff check --fix src/shared src/mo_toc src/build_mo_toc.py src/web_toc src/build_web_toc.py tests
ruff format src/shared src/mo_toc src/build_mo_toc.py src/web_toc src/build_web_toc.py tests
radon cc -s -n B src/shared src/mo_toc src/build_mo_toc.py src/web_toc src/build_web_toc.py tests
vulture src/shared src/mo_toc src/build_mo_toc.py src/web_toc src/build_web_toc.py tests
pytest --cov=src/shared --cov=src/mo_toc --cov=src.build_mo_toc --cov=src/web_toc --cov=src.build_web_toc
pytest -q
```

All green, all new branches covered (`_number_for`'s canonical/marker split, the
fallback-to-type-name path, and the `parent_number == ""` vs. non-empty path in
`assign_unified_numbers`/`_number_for` are all directly exercised by Task 1's tests).
