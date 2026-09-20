# BC Building Code (Web) — Table of Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth tab to the MO Package viewer — a hierarchical Table of Images sourced
from the live BC Building Code website (`https://dev.buildingcode.gov.bc.ca`), built from its
`navigation-tree.json` and per-section content JSON, with a build step (`build_web_toc.py`)
that mirrors `build_mo_toc.py`'s shape but writes `output/web_toc.json` instead of touching
the PDF pipeline at all.

**Architecture:** A new, fully independent package `src/web_toc/` (domain/parsing/output,
same Clean Architecture split as `mo_toc/`). Images are matched to their owning node by
string-prefix matching on the site's own hierarchical ids (no position math needed, unlike
the PDF's bbox-based `image_matcher.py`). The web layer (`mo_toc/web/api.py`,
`serve_mo_toc.py`, `index.html`, `viewer.js`) gets additive-only changes: a new optional
parameter, a new route, a new tab, new render functions. Every existing route, tab, and test
keeps its current behavior.

**Tech Stack:** Python 3.11+, `httpx` (already in `requirements.txt` — no new dependency),
FastAPI, vanilla JS (no build step, matching the existing viewer).

**Spec:** [ai_docs/2026-09-20-web-toc-images-design.md](../2026-09-20-web-toc-images-design.md)

## Global Constraints

- TDD strictly for every Python change: failing test → minimum code → pass → refactor. The
  frontend (`index.html`/`viewer.js`) has no existing automated test harness in this repo
  (the current three tabs were verified manually via the Browser pane tool, not unit tests) —
  Task 9 follows that same precedent and is verified manually, not with new test infra.
- **Nothing under `src/mo_toc/`, `src/build_mo_toc.py`, or any existing test may have its
  behavior changed.** Where a task must touch a shared file (`mo_toc/web/api.py`,
  `serve_mo_toc.py`, `tests/test_api.py`, `tests/test_serve_mo_toc.py`), the change is
  strictly additive: new optional parameters with safe defaults, new routes, new test
  functions. Every existing test in those files must still pass unmodified, and no existing
  test's assertions may change.
- No new pip dependency: `httpx>=0.27.0` is already in `requirements.txt` and is the HTTP
  client for the whole `web_toc` package.
- Real network calls only inside `@pytest.mark.slow`-marked tests (the default `pytest -q`
  run must never touch the network). Everything else fakes `WebSource`/`httpx.get`.
- Base URL and site version are CLI flags on `build_web_toc.py`, never hardcoded past their
  default values, so tests and future site changes don't require code edits.
- Definition-of-done commands (`ruff`, `radon`, `vulture`, `pytest --cov`) run scoped to
  `src/mo_toc src/build_mo_toc.py src/serve_mo_toc.py src/web_toc src/build_web_toc.py tests`
  — the existing scope, extended with the two new paths — never the whole repo.

---

### Task 1: `web_toc` domain models

**Files:**
- Create: `src/web_toc/__init__.py` (empty)
- Create: `src/web_toc/domain/__init__.py` (empty)
- Create: `src/web_toc/domain/models.py`
- Test: `tests/test_web_toc_domain_models.py`

**Interfaces:**
- Produces: `WebNode(type: str, identifier: str, citation: str, title: str, path: str, children: list["WebNode"] = [])`, `WebImage(id: str, src: str, alt_text: str, owner_citation: str)`. Every later task imports both from `web_toc.domain.models`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_toc_domain_models.py
from web_toc.domain.models import WebImage, WebNode


def test_web_node_defaults_to_no_children():
    node = WebNode(type="section", identifier="1.1", citation="nbc.divA.part1.sect1",
                    title="General", path="/code/nbc.divA/1/1")
    assert node.children == []


def test_web_node_children_are_independent_between_instances():
    a = WebNode(type="part", identifier="1", citation="nbc.divA.part1", title="", path="/code/nbc.divA/1")
    b = WebNode(type="part", identifier="2", citation="nbc.divA.part2", title="", path="/code/nbc.divA/2")
    a.children.append("x")
    assert b.children == []


def test_web_node_holds_nested_children():
    child = WebNode(type="article", identifier="1.1.1.1", citation="nbc.divA.part1.sect1.subsect1.art1",
                     title="Application", path="/code/nbc.divA/1/1/1/1")
    parent = WebNode(type="subsection", identifier="1.1.1", citation="nbc.divA.part1.sect1.subsect1",
                      title="Application", path="/code/nbc.divA/1/1/1", children=[child])
    assert parent.children[0].citation == "nbc.divA.part1.sect1.subsect1.art1"


def test_web_image_holds_graphic_and_owner_fields():
    img = WebImage(id="nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23",
                    src="bc-graphics/gg00556a", alt_text="Three storey building configuration",
                    owner_citation="nbc.divBV2.part9.sect23.subsect13.art7")
    assert img.src == "bc-graphics/gg00556a"
    assert img.owner_citation == "nbc.divBV2.part9.sect23.subsect13.art7"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_toc_domain_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_toc/domain/models.py
from dataclasses import dataclass, field


@dataclass
class WebNode:
    type: str
    identifier: str
    citation: str
    title: str
    path: str
    children: list["WebNode"] = field(default_factory=list)


@dataclass
class WebImage:
    id: str
    src: str
    alt_text: str
    owner_citation: str
```

Also create empty `src/web_toc/__init__.py` and `src/web_toc/domain/__init__.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_web_toc_domain_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/__init__.py src/web_toc/domain/__init__.py src/web_toc/domain/models.py tests/test_web_toc_domain_models.py
git commit -m "feat(web_toc): add WebNode/WebImage domain models"
```

---

### Task 2: Content URL dispatch (`content_url.py`)

**Files:**
- Create: `src/web_toc/parsing/__init__.py` (empty)
- Create: `src/web_toc/parsing/content_url.py`
- Test: `tests/test_web_toc_content_url.py`

**Interfaces:**
- Consumes: `WebNode` from Task 1.
- Produces: `content_url(node: WebNode, version: str) -> str | None`. Task 7 (`build_web_toc.py`) calls this once per node during its walk.

The URL rules below were verified against the live site by direct HTTP requests (see the
design doc). `{div}` in each regex is everything before `.partN`/`.appendixX`, e.g.
`nbc.divA`, `nbc.divBV2`, `nbc.divC` — lowercased with `.` replaced by `-` for the URL.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_toc_content_url.py
from web_toc.domain.models import WebNode
from web_toc.parsing.content_url import content_url


def _node(node_type, citation, path=""):
    return WebNode(type=node_type, identifier="", citation=citation, title="", path=path)


def test_section_node_returns_section_url():
    node = _node("section", "nbc.divA.part1.sect1")
    assert content_url(node, "2024") == "/data/2024/content/nbc-diva/part-1/section-1.json"


def test_section_node_under_second_volume_division_slug():
    node = _node("section", "nbc.divBV2.part9.sect23")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divbv2/part-9/section-23.json"


def test_part_appendix_node_returns_appendix_url():
    node = _node("part_appendix", "nbc.divBV2.part9.appendix")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divbv2/part-9/appendix.json"


def test_division_appendix_node_lowercases_letter():
    node = _node("division_appendix", "nbc.divB.appendixC")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divb/appendix-c.json"


def test_spectables_node_returns_spectables_url():
    node = _node("spectables", "nbc.divBV2.part9.spectables1")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divbv2/part-9/spectables/1.json"


def test_front_matter_article_uses_last_path_segment():
    node = _node("article", "nbc.2020.preface", path="/code/front-matter/preface")
    assert content_url(node, "2024") == "/data/2024/content/front-matter/preface.json"


def test_regular_article_returns_none():
    # A non-front-matter article's figures are covered by its parent section's
    # own content fetch - it never gets its own content URL.
    node = _node("article", "nbc.divA.part1.sect1.subsect1.art1", path="/code/nbc.divA/1/1/1/1")
    assert content_url(node, "2024") is None


def test_index_and_conversions_return_none():
    assert content_url(_node("index", "nbc.2020.vol2.index"), "2024") is None
    assert content_url(_node("conversions", "nbc.2020.vol2.conversions"), "2024") is None


def test_structural_types_return_none():
    for node_type in ("volume", "division", "part", "subsection"):
        assert content_url(_node(node_type, "nbc.divA"), "2024") is None


def test_version_is_used_in_url():
    node = _node("section", "nbc.divA.part1.sect1")
    assert content_url(node, "2020") == "/data/2020/content/nbc-diva/part-1/section-1.json"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_toc_content_url.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_toc/parsing/content_url.py
"""Derives each content-bearing node's own content-JSON URL directly from its
id/path - no ancestor traversal needed, since the site's own ids already
encode the full division/part/section chain (verified against the live site;
see ai_docs/2026-09-20-web-toc-images-design.md). `index`/`conversions` nodes
and regular (non-front-matter) articles return None: no working URL was found
for the former, and the latter's figures are already covered by their parent
section's own content fetch.
"""
import re

from web_toc.domain.models import WebNode

_SECTION_RE = re.compile(r"^(?P<div>.+)\.part(?P<part>\d+)\.sect(?P<sect>\d+)$")
_PART_APPENDIX_RE = re.compile(r"^(?P<div>.+)\.part(?P<part>\d+)\.appendix$")
_DIVISION_APPENDIX_RE = re.compile(r"^(?P<div>.+)\.appendix(?P<letter>[A-Za-z])$")
_SPECTABLES_RE = re.compile(r"^(?P<div>.+)\.part(?P<part>\d+)\.spectables(?P<num>\d+)$")


def _div_slug(div_id: str) -> str:
    return div_id.lower().replace(".", "-")


def content_url(node: WebNode, version: str) -> str | None:
    base = f"/data/{version}/content"
    if node.type == "section":
        m = _SECTION_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/part-{m['part']}/section-{m['sect']}.json" if m else None
    if node.type == "part_appendix":
        m = _PART_APPENDIX_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/part-{m['part']}/appendix.json" if m else None
    if node.type == "division_appendix":
        m = _DIVISION_APPENDIX_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/appendix-{m['letter'].lower()}.json" if m else None
    if node.type == "spectables":
        m = _SPECTABLES_RE.match(node.citation)
        return f"{base}/{_div_slug(m['div'])}/part-{m['part']}/spectables/{m['num']}.json" if m else None
    if node.type == "article" and node.path.startswith("/code/front-matter/"):
        slug = node.path.rstrip("/").rsplit("/", 1)[-1]
        return f"{base}/front-matter/{slug}.json"
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_web_toc_content_url.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/__init__.py src/web_toc/parsing/content_url.py tests/test_web_toc_content_url.py
git commit -m "feat(web_toc): add content-URL dispatch per node type"
```

---

### Task 3: Tree builder (`tree_builder.py`)

**Files:**
- Create: `src/web_toc/parsing/tree_builder.py`
- Test: `tests/test_web_toc_tree_builder.py`

**Interfaces:**
- Consumes: `WebNode` from Task 1.
- Produces: `build_tree(nav_data: dict) -> WebNode` and `collect_citations(node: WebNode) -> set[str]`. Task 7 calls both; Task 4 (`image_extractor.py`) consumes the `set[str]` `collect_citations` returns.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_toc_tree_builder.py
from web_toc.parsing.tree_builder import build_tree, collect_citations


def _nav_fixture():
    return {
        "tree": [
            {
                "id": "nbc.2020.vol1", "type": "volume", "number": "1", "title": "Volume 1",
                "path": "/volume/1",
                "children": [
                    {
                        "id": "nbc.divA", "type": "division", "title": "Division A", "path": "/code/nbc.divA",
                        "children": [
                            {
                                "id": "nbc.divA.part1", "type": "part", "number": "1", "title": "Part 1",
                                "path": "/code/nbc.divA/1",
                                "children": [
                                    {
                                        "id": "nbc.divA.part1.sect1", "type": "section", "number": "1.1",
                                        "title": "1.1 General", "path": "/code/nbc.divA/1/1",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "id": "nbc.divBV2.part9", "type": "part", "number": "9", "title": "Part 9",
                "path": "/code/nbc.divBV2/9",
            },
        ]
    }


def test_build_tree_wraps_top_level_entries_under_a_root():
    root = build_tree(_nav_fixture())
    assert root.type == "root"
    assert len(root.children) == 2


def test_build_tree_preserves_nested_children():
    root = build_tree(_nav_fixture())
    volume = root.children[0]
    division = volume.children[0]
    part = division.children[0]
    section = part.children[0]
    assert [volume.type, division.type, part.type, section.type] == ["volume", "division", "part", "section"]
    assert section.citation == "nbc.divA.part1.sect1"
    assert section.identifier == "1.1"


def test_build_tree_defaults_identifier_to_empty_string_when_number_missing():
    root = build_tree(_nav_fixture())
    division = root.children[0].children[0]
    assert division.identifier == ""


def test_build_tree_leaf_node_has_no_children():
    root = build_tree(_nav_fixture())
    section = root.children[0].children[0].children[0].children[0]
    assert section.children == []


def test_collect_citations_includes_root_and_every_descendant():
    root = build_tree(_nav_fixture())
    citations = collect_citations(root)
    assert "root" in citations
    assert "nbc.divA.part1.sect1" in citations
    assert "nbc.divBV2.part9" in citations
    assert len(citations) == 6  # root + volume + division + part + section + part9


def test_collect_citations_on_leaf_node_returns_single_citation():
    root = build_tree(_nav_fixture())
    section = root.children[0].children[0].children[0].children[0]
    assert collect_citations(section) == {"nbc.divA.part1.sect1"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_toc_tree_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing.tree_builder'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_toc/parsing/tree_builder.py
from web_toc.domain.models import WebNode


def build_tree(nav_data: dict) -> WebNode:
    return WebNode(
        type="root",
        identifier="",
        citation="root",
        title="BC Building Code",
        path="/",
        children=[_convert(raw) for raw in nav_data["tree"]],
    )


def _convert(raw: dict) -> WebNode:
    return WebNode(
        type=raw["type"],
        identifier=str(raw.get("number", "")),
        citation=raw["id"],
        title=raw.get("title", ""),
        path=raw.get("path", ""),
        children=[_convert(child) for child in raw.get("children", [])],
    )


def collect_citations(node: WebNode) -> set[str]:
    citations = {node.citation}
    for child in node.children:
        citations |= collect_citations(child)
    return citations
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_web_toc_tree_builder.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/tree_builder.py tests/test_web_toc_tree_builder.py
git commit -m "feat(web_toc): build WebNode tree from navigation-tree.json"
```

---

### Task 4: Image extractor (`image_extractor.py`)

**Files:**
- Create: `src/web_toc/parsing/image_extractor.py`
- Test: `tests/test_web_toc_image_extractor.py`

**Interfaces:**
- Consumes: `WebImage` from Task 1.
- Produces: `extract_images(content: dict, citations: set[str], fallback_citation: str) -> list[WebImage]`. Task 7 calls this once per fetched content JSON, passing `collect_citations(root)` (Task 3) and the citation of the node whose content is being fetched as `fallback_citation`.

Owner assignment: strip trailing `.`-segments off a figure's own `id` until the remainder is
a known citation (exact match against `citations`). If nothing matches even after stripping
everything, fall back to `fallback_citation` — the node whose content we're already inside, so
no image is ever dropped (refines the design doc's "dropped, logged" language: a total loss
turned out to be avoidable, since we always know at least the enclosing section/appendix).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_toc_image_extractor.py
from web_toc.parsing.image_extractor import extract_images


def test_figure_matches_deepest_ancestor_citation():
    citations = {"nbc.divA.part1.sect1", "nbc.divA.part1.sect1.subsect1.art1"}
    content = {
        "id": "nbc.divA.part1.sect1",
        "subsections": [{"articles": [{"content": [
            {"type": "figure", "id": "nbc.divA.part1.sect1.subsect1.art1.sent1.figure1",
             "graphic": {"src": "bc-graphics/x1", "alt_text": "Diagram"}}
        ]}]}],
    }
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert len(images) == 1
    assert images[0].owner_citation == "nbc.divA.part1.sect1.subsect1.art1"
    assert images[0].src == "bc-graphics/x1"
    assert images[0].alt_text == "Diagram"


def test_figure_falls_back_to_enclosing_node_when_no_deeper_match():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "id": "nbc.divA.part1.sect1",
        "subsections": [{"articles": [{"content": [
            {"type": "figure", "id": "nbc.divA.part1.sect1.subsect9.art9.sent1.figure1",
             "graphic": {"src": "bc-graphics/x2", "alt_text": "Untracked subsection"}}
        ]}]}],
    }
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert images[0].owner_citation == "nbc.divA.part1.sect1"


def test_figures_nested_inside_table_cells_are_found():
    citations = {"nbc.divBV2.part9.sect23.subsect13.art7"}
    content = {
        "id": "nbc.divBV2.part9.sect23",
        "subsections": [{"articles": [{
            "id": "nbc.divBV2.part9.sect23.subsect13.art7",
            "content": [{"structure": {"body_rows": [
                {"cells": [{"content": [
                    {"type": "figure", "id": "nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23",
                     "graphic": {"src": "bc-graphics/gg00556a", "alt_text": "Three storey building configuration"}}
                ]}]}
            ]}}],
        }]}],
    }
    images = extract_images(content, citations, fallback_citation="nbc.divBV2.part9.sect23")
    assert len(images) == 1
    assert images[0].owner_citation == "nbc.divBV2.part9.sect23.subsect13.art7"


def test_multiple_figures_in_one_content_json_are_all_extracted():
    citations = {"nbc.divA.part1.sect1"}
    content = {"content": [
        {"type": "figure", "id": "nbc.divA.part1.sect1.figA", "graphic": {"src": "a", "alt_text": "A"}},
        {"type": "figure", "id": "nbc.divA.part1.sect1.figB", "graphic": {"src": "b", "alt_text": "B"}},
    ]}
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert {img.src for img in images} == {"a", "b"}


def test_no_figures_returns_empty_list():
    content = {"id": "nbc.divA.part1.sect1", "subsections": []}
    assert extract_images(content, {"nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_toc_image_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing.image_extractor'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_toc/parsing/image_extractor.py
"""Walks one section/appendix/spectables/front-matter-article content JSON
for {"type": "figure", ...} nodes, wherever they're nested (directly in an
article's content, or inside a table cell), and assigns each one an owner by
stripping trailing dot-segments off its own id until the remainder matches a
real node's citation. Every figure's id already encodes its full ancestor
chain, so - unlike the PDF pipeline's image_matcher.py - no position/bbox
comparison is needed here at all.
"""
from web_toc.domain.models import WebImage


def _resolve_owner(figure_id: str, citations: set[str], fallback_citation: str) -> str:
    parts = figure_id.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in citations:
            return candidate
        parts.pop()
    return fallback_citation


def _walk_figures(node):
    if isinstance(node, dict):
        if node.get("type") == "figure":
            yield node
        for value in node.values():
            yield from _walk_figures(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_figures(item)


def extract_images(content: dict, citations: set[str], fallback_citation: str) -> list[WebImage]:
    images = []
    for figure in _walk_figures(content):
        graphic = figure.get("graphic", {})
        owner = _resolve_owner(figure["id"], citations, fallback_citation)
        images.append(
            WebImage(
                id=figure["id"],
                src=graphic.get("src", ""),
                alt_text=graphic.get("alt_text", ""),
                owner_citation=owner,
            )
        )
    return images
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_web_toc_image_extractor.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/image_extractor.py tests/test_web_toc_image_extractor.py
git commit -m "feat(web_toc): extract figures with id-prefix owner matching"
```

---

### Task 5: JSON writer (`json_writer.py`)

**Files:**
- Create: `src/web_toc/output/__init__.py` (empty)
- Create: `src/web_toc/output/json_writer.py`
- Test: `tests/test_web_toc_json_writer.py`

**Interfaces:**
- Consumes: `WebNode`, `WebImage` from Task 1.
- Produces: `write_json(root: WebNode, images: list[WebImage], out_path: str) -> None`, writing `{"tree": ..., "images": [...]}`. Task 7 calls this as its last step; Task 8 (`mo_toc/web/api.py`) reads this exact JSON shape back.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_toc_json_writer.py
import json

from web_toc.domain.models import WebImage, WebNode
from web_toc.output.json_writer import write_json


def test_write_json_roundtrips_tree_and_images(tmp_path):
    child = WebNode(type="section", identifier="1.1", citation="nbc.divA.part1.sect1",
                     title="General", path="/code/nbc.divA/1/1")
    root = WebNode(type="root", identifier="", citation="root", title="BC Building Code",
                    path="/", children=[child])
    image = WebImage(id="nbc.divA.part1.sect1.fig1", src="bc-graphics/x", alt_text="Diagram",
                      owner_citation="nbc.divA.part1.sect1")

    out_path = tmp_path / "web_toc.json"
    write_json(root, [image], str(out_path))

    payload = json.loads(out_path.read_text())
    assert payload["tree"]["type"] == "root"
    assert payload["tree"]["children"][0]["citation"] == "nbc.divA.part1.sect1"
    assert payload["images"][0]["src"] == "bc-graphics/x"


def test_write_json_creates_parent_directories(tmp_path):
    root = WebNode(type="root", identifier="", citation="root", title="", path="/")
    out_path = tmp_path / "nested" / "web_toc.json"
    write_json(root, [], str(out_path))
    assert out_path.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_toc_json_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.output'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_toc/output/json_writer.py
import dataclasses
import json
from pathlib import Path

from web_toc.domain.models import WebImage, WebNode


def write_json(root: WebNode, images: list[WebImage], out_path: str) -> None:
    payload = {
        "tree": dataclasses.asdict(root),
        "images": [dataclasses.asdict(i) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_web_toc_json_writer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/output/__init__.py src/web_toc/output/json_writer.py tests/test_web_toc_json_writer.py
git commit -m "feat(web_toc): write output/web_toc.json"
```

---

### Task 6: HTTP source adapter (`site_source.py`)

**Files:**
- Create: `src/web_toc/parsing/site_source.py`
- Test: `tests/test_web_toc_site_source.py`

**Interfaces:**
- Produces: `WebSource` (a `Protocol` with `fetch_navigation_tree() -> dict` and `fetch_content(path: str) -> dict | None`) and `HttpxWebSource(base_url: str, version: str)` implementing it. Task 7 instantiates `HttpxWebSource` directly; Task 7's own test fakes `WebSource`.

`fetch_content` must treat any non-JSON response (the site's Next.js fallback returns HTTP 200
with an HTML page for an unmatched `/data/...` path — confirmed live) as "nothing here" rather
than raising, since `content_url`'s regexes won't be right for every edge case.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_toc_site_source.py
from unittest.mock import MagicMock, patch

from web_toc.parsing.site_source import HttpxWebSource


def _fake_response(text, status_code=200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.json.return_value = __import__("json").loads(text) if text.strip().startswith("{") else None
    resp.raise_for_status = MagicMock()
    return resp


@patch("web_toc.parsing.site_source.httpx.get")
def test_fetch_navigation_tree_requests_the_correct_url(mock_get):
    mock_get.return_value = _fake_response('{"tree": []}')
    source = HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024")

    result = source.fetch_navigation_tree()

    mock_get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/navigation-tree.json", timeout=30.0
    )
    assert result == {"tree": []}


@patch("web_toc.parsing.site_source.httpx.get")
def test_fetch_content_builds_url_from_base_and_path(mock_get):
    mock_get.return_value = _fake_response('{"id": "nbc.divA.part1.sect1"}')
    source = HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024")

    result = source.fetch_content("/data/2024/content/nbc-diva/part-1/section-1.json")

    mock_get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/content/nbc-diva/part-1/section-1.json",
        timeout=30.0,
    )
    assert result == {"id": "nbc.divA.part1.sect1"}


@patch("web_toc.parsing.site_source.httpx.get")
def test_fetch_content_returns_none_for_html_fallback_response(mock_get):
    mock_get.return_value = _fake_response("<!DOCTYPE html><html>...</html>")
    source = HttpxWebSource("https://dev.buildingcode.gov.bc.ca", "2024")

    assert source.fetch_content("/data/2024/content/bogus/nope.json") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_web_toc_site_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web_toc.parsing.site_source'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_toc/parsing/site_source.py
from typing import Protocol

import httpx


class WebSource(Protocol):
    def fetch_navigation_tree(self) -> dict: ...
    def fetch_content(self, path: str) -> dict | None: ...


class HttpxWebSource:
    def __init__(self, base_url: str, version: str):
        self._base_url = base_url.rstrip("/")
        self._version = version

    def fetch_navigation_tree(self) -> dict:
        url = f"{self._base_url}/data/{self._version}/navigation-tree.json"
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        return response.json()

    def fetch_content(self, path: str) -> dict | None:
        url = f"{self._base_url}{path}"
        response = httpx.get(url, timeout=30.0)
        if not response.text.strip().startswith("{"):
            return None
        return response.json()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_web_toc_site_source.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_toc/parsing/site_source.py tests/test_web_toc_site_source.py
git commit -m "feat(web_toc): add httpx-backed WebSource adapter"
```

---

### Task 7: Build orchestrator (`build_web_toc.py`)

**Files:**
- Create: `src/build_web_toc.py`
- Test: `tests/test_build_web_toc.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6 (`WebNode`/`WebImage`, `content_url`, `build_tree`/`collect_citations`, `extract_images`, `write_json`, `HttpxWebSource`).
- Produces: `run(base_url: str, version: str, output_dir: str) -> None` and CLI `main()`. This is the script the user runs directly (`python3 src/build_web_toc.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_build_web_toc.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from build_web_toc import run
from web_toc.domain.models import WebNode


@patch("build_web_toc.write_json")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_wires_pipeline_and_writes_images_from_every_content_bearing_node(
    mock_source_cls, mock_build_tree, mock_collect_citations,
    mock_content_url, mock_extract_images, mock_write_json, tmp_path,
):
    leaf = WebNode(type="section", identifier="1.1", citation="nbc.divA.part1.sect1", title="", path="")
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = MagicMock()
    mock_source_cls.return_value = mock_source
    mock_source.fetch_navigation_tree.return_value = {"tree": []}
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.divA.part1.sect1"}
    # root has no content URL, the leaf section does
    mock_content_url.side_effect = lambda node, version: (
        "/data/2024/content/nbc-diva/part-1/section-1.json" if node is leaf else None
    )
    mock_source.fetch_content.return_value = {"id": "nbc.divA.part1.sect1"}
    mock_extract_images.return_value = ["WEB_IMAGE"]

    run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path))

    mock_source_cls.assert_called_once_with("https://dev.buildingcode.gov.bc.ca", "2024")
    mock_build_tree.assert_called_once_with({"tree": []})
    mock_collect_citations.assert_called_once_with(root)
    mock_source.fetch_content.assert_called_once_with("/data/2024/content/nbc-diva/part-1/section-1.json")
    mock_extract_images.assert_called_once_with(
        {"id": "nbc.divA.part1.sect1"}, {"root", "nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1"
    )
    mock_write_json.assert_called_once_with(root, ["WEB_IMAGE"], str(Path(tmp_path) / "web_toc.json"))


@patch("build_web_toc.write_json")
@patch("build_web_toc.extract_images")
@patch("build_web_toc.content_url")
@patch("build_web_toc.collect_citations")
@patch("build_web_toc.build_tree")
@patch("build_web_toc.HttpxWebSource")
def test_run_skips_nodes_where_fetch_content_returns_none(
    mock_source_cls, mock_build_tree, mock_collect_citations,
    mock_content_url, mock_extract_images, mock_write_json, tmp_path,
):
    leaf = WebNode(type="index", identifier="", citation="nbc.2020.vol2.index", title="", path="")
    root = WebNode(type="root", identifier="", citation="root", title="", path="", children=[leaf])
    mock_source = MagicMock()
    mock_source_cls.return_value = mock_source
    mock_build_tree.return_value = root
    mock_collect_citations.return_value = {"root", "nbc.2020.vol2.index"}
    mock_content_url.return_value = None  # index/conversions: no URL at all

    run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path))

    mock_source.fetch_content.assert_not_called()
    mock_extract_images.assert_not_called()
    mock_write_json.assert_called_once_with(root, [], str(Path(tmp_path) / "web_toc.json"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_build_web_toc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_web_toc'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
# src/build_web_toc.py
"""Parses the live BC Building Code website's navigation tree + per-section
content into output/web_toc.json: a hierarchical index plus every embedded
figure, matched to the deepest document node it belongs to.

Usage:
    python3 src/build_web_toc.py
    python3 src/build_web_toc.py --base-url https://dev.buildingcode.gov.bc.ca --version 2024
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web_toc.output.json_writer import write_json
from web_toc.parsing.content_url import content_url
from web_toc.parsing.image_extractor import extract_images
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.tree_builder import build_tree, collect_citations

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://dev.buildingcode.gov.bc.ca"
DEFAULT_VERSION = "2024"
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def run(base_url: str, version: str, output_dir: str) -> None:
    source = HttpxWebSource(base_url, version)
    root = build_tree(source.fetch_navigation_tree())
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(f"Parsing {args.base_url} (version {args.version}) ...", file=sys.stderr)
    run(args.base_url, args.version, args.output_dir)
    print(f"Wrote {args.output_dir}/web_toc.json", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_build_web_toc.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/build_web_toc.py tests/test_build_web_toc.py
git commit -m "feat(web_toc): add build_web_toc.py orchestrator CLI"
```

---

### Task 8: Wire `/api/web-toc` into the existing viewer app (additive)

**Files:**
- Modify: `src/mo_toc/web/api.py` — add optional `web_toc_json_path` parameter and a new `/api/web-toc` route. Every existing parameter, route, and response shape is unchanged.
- Modify: `src/serve_mo_toc.py` — add `WEB_TOC_JSON` path constant and pass it through `_get_app()`. `TOC_JSON`/`PDF_PATH`/`THUMBNAILS_DIR` handling and the existing "missing PDF index" `sys.exit` are unchanged.
- Modify (additive only — append new tests, do not change existing ones): `tests/test_api.py`, `tests/test_serve_mo_toc.py`.

**Interfaces:**
- Consumes: the `{"tree": ..., "images": [...]}` shape Task 5's `write_json` produces.
- Produces: `GET /api/web-toc` → 200 with that payload when `output/web_toc.json` exists, 503 with a helpful message otherwise. Task 9 (frontend) calls this endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py` (do not modify `_write_fixture_json`, `_make_client`'s existing
callers, or any existing test function):

```python
def _write_web_toc_fixture(tmp_path):
    payload = {
        "tree": {"type": "root", "identifier": "", "citation": "root", "title": "", "path": "/", "children": []},
        "images": [{"id": "fig1", "src": "bc-graphics/x", "alt_text": "alt", "owner_citation": "root"}],
    }
    path = tmp_path / "web_toc.json"
    path.write_text(json.dumps(payload))
    return str(path)


def test_get_web_toc_returns_payload_when_present(tmp_path):
    web_toc_json_path = _write_web_toc_fixture(tmp_path)
    client = _make_client(tmp_path, web_toc_json_path=web_toc_json_path)
    resp = client.get("/api/web-toc")
    assert resp.status_code == 200
    assert resp.json()["images"][0]["src"] == "bc-graphics/x"


def test_get_web_toc_returns_503_when_not_built(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/web-toc")
    assert resp.status_code == 503
```

And change `_make_client`'s signature (the only change to existing code in this file — every
existing call site keeps working unmodified since the new parameter defaults to `None`):

```python
def _make_client(tmp_path, pdf_path=None, create_thumbnail=True, web_toc_json_path=None):
    ...
    app = create_app(
        toc_json_path=json_path,
        pdf_path=str(pdf_path),
        thumbnails_dir=str(thumbs_dir),
        web_toc_json_path=web_toc_json_path,
    )
    return TestClient(app)
```

Append to `tests/test_serve_mo_toc.py`:

```python
def test_app_returns_503_for_web_toc_when_web_toc_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(serve_mo_toc, "WEB_TOC_JSON", str(tmp_path / "missing_web_toc.json"))
    client = _make_client(tmp_path)
    resp = client.get("/api/web-toc")
    assert resp.status_code == 503
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_api.py tests/test_serve_mo_toc.py -v`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'web_toc_json_path'` (and `AttributeError` for `serve_mo_toc.WEB_TOC_JSON`)

- [ ] **Step 3: Write minimal implementation**

In `src/mo_toc/web/api.py`, change the signature and add the payload load + route (everything
else in the file is unchanged):

```python
def create_app(
    toc_json_path: str,
    pdf_path: str,
    thumbnails_dir: str,
    web_toc_json_path: str | None = None,
) -> FastAPI:
    app = FastAPI(title="MO Package TOC Viewer")
    payload = json.loads(Path(toc_json_path).read_text())
    web_payload = None
    if web_toc_json_path and Path(web_toc_json_path).exists():
        web_payload = json.loads(Path(web_toc_json_path).read_text())

    @app.get("/api/toc")
    def get_toc():
        return JSONResponse(payload["volume"])

    @app.get("/api/images")
    def get_images():
        return JSONResponse(payload["images"])

    @app.get("/api/web-toc")
    def get_web_toc():
        if web_payload is None:
            raise HTTPException(status_code=503, detail="Run src/build_web_toc.py first")
        return JSONResponse(web_payload)

    @app.get("/pdf")
    def get_pdf():
        return FileResponse(pdf_path, media_type="application/pdf")

    @app.get("/api/image/{index}/thumbnail")
    def get_thumbnail(index: int):
        if index < 0 or index >= len(payload["images"]):
            raise HTTPException(status_code=404, detail="No such image")
        rel_path = payload["images"][index]["thumbnail_path"]
        file_path = Path(thumbnails_dir).parent / rel_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file missing")
        return FileResponse(str(file_path))

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(static_dir / "index.html"))

    return app
```

In `src/serve_mo_toc.py`, add the new constant and pass it through (everything else unchanged):

```python
TOC_JSON = str(PROJECT_ROOT / "output" / "mo_toc.json")
PDF_PATH = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
THUMBNAILS_DIR = str(PROJECT_ROOT / "output" / "thumbnails")
WEB_TOC_JSON = str(PROJECT_ROOT / "output" / "web_toc.json")

_app = None


def _get_app():
    global _app
    if _app is None:
        if not Path(TOC_JSON).exists():
            sys.exit(f"No such file: {TOC_JSON} (run src/build_mo_toc.py first)")
        web_toc_json = WEB_TOC_JSON if Path(WEB_TOC_JSON).exists() else None
        _app = create_app(
            toc_json_path=TOC_JSON,
            pdf_path=PDF_PATH,
            thumbnails_dir=THUMBNAILS_DIR,
            web_toc_json_path=web_toc_json,
        )
    return _app
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_api.py tests/test_serve_mo_toc.py -v`
Expected: PASS — all previously-existing tests in both files still pass, plus the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/web/api.py src/serve_mo_toc.py tests/test_api.py tests/test_serve_mo_toc.py
git commit -m "feat: wire GET /api/web-toc into the viewer app (additive)"
```

---

### Task 9: Fourth tab — "BC Code (Web) — Table of Images" (frontend)

**Files:**
- Modify: `src/mo_toc/web/static/index.html` — add a 4th tab button, its content div, and a
  detail panel. All three existing tabs' markup is untouched.
- Modify: `src/mo_toc/web/static/style.css` — add rules for the new `#web-image-detail` panel
  only (new selector; nothing existing is edited). Image rows reuse the existing
  `.image-row`/`.node-row` classes, so no new CSS is needed for them.
- Modify: `src/mo_toc/web/static/viewer.js` — add the new tab's data loading, tree rendering,
  and detail panel; extend `TABS`/`TAB_CONTENT_ID` and `init()`; bump the cache-bust query
  string. Every existing function (`loadToc`, `loadImages`, `loadImageTree`, `goToLocation`,
  `showHighlight`, etc.) is untouched.

**No automated tests** — this repo has no JS test harness, and the existing three tabs were
verified the same way (manually, via the Browser pane tool). Step 3 below is manual
verification against the built app, not `pytest`.

- [ ] **Step 1: Add the 4th tab, its content div, and the detail panel to `index.html`**

```html
<!-- inside <div id="tabs">, after the existing "tab-image-tree" button -->
<button id="tab-web-images">BC Code (Web)</button>
```

```html
<!-- inside #sidebar, after the existing "image-tree" div -->
<div id="web-images" style="display:none">
  <div id="web-image-tree-content"></div>
</div>
```

```html
<!-- inside #main, after the existing #highlight div -->
<div id="web-image-detail" style="display:none">
  <button id="web-image-detail-close">&times;</button>
  <img id="web-image-detail-img">
  <div id="web-image-detail-alt"></div>
  <div id="web-image-detail-citation"></div>
  <a id="web-image-detail-link" target="_blank" rel="noopener">View on official site &#8599;</a>
</div>
```

Bump the script tag's cache-bust query string: `<script type="module" src="/static/viewer.js?v=4"></script>`.

- [ ] **Step 2: Add the detail panel styling to `style.css`**

```css
#web-image-detail {
  position: fixed; top: 60px; right: 20px; width: 320px;
  background: #fff; border: 1px solid #ccc; padding: var(--gap);
  box-shadow: 0 2px 8px rgba(0,0,0,0.2); text-align: left;
}
#web-image-detail img { max-width: 100%; display: block; margin-bottom: var(--gap); }
#web-image-detail-close { float: right; border: none; background: none; cursor: pointer; font-size: 1.2em; }
```

- [ ] **Step 3: Add the tab's logic to `viewer.js`**

Add near the other tree-rendering functions (after `loadImageTree`):

```javascript
function webImageUrl(img) {
  return `https://dev.buildingcode.gov.bc.ca/${img.src}.jpg`;
}

function buildWebCitationMap(node, map) {
  map[node.citation] = node;
  node.children.forEach((child) => buildWebCitationMap(child, map));
  return map;
}

function clearAttachedWebImages(node) {
  delete node._images;
  node.children.forEach(clearAttachedWebImages);
}

function attachWebImagesToOwners(tree, images) {
  clearAttachedWebImages(tree);
  const citationMap = buildWebCitationMap(tree, {});
  images.forEach((img) => {
    const owner = citationMap[img.owner_citation];
    if (!owner) return;
    if (!owner._images) owner._images = [];
    owner._images.push(img);
  });
}

function subtreeHasWebImages(node) {
  if (node._images && node._images.length > 0) return true;
  return node.children.some(subtreeHasWebImages);
}

function showWebImageDetail(img, ownerNode) {
  document.getElementById("web-image-detail-img").src = webImageUrl(img);
  document.getElementById("web-image-detail-alt").textContent = img.alt_text || "(no description)";
  document.getElementById("web-image-detail-citation").textContent =
    `${ownerNode.type} ${ownerNode.identifier} ${ownerNode.title}`.trim();
  document.getElementById("web-image-detail-link").href =
    `https://dev.buildingcode.gov.bc.ca${ownerNode.path}?version=2024&date=2024-03-08`;
  document.getElementById("web-image-detail").style.display = "block";
}

function renderWebImageRow(img, ownerNode, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="${webImageUrl(img)}" loading="lazy"> ${img.alt_text || "(no description)"}`;
  row.addEventListener("click", () => showWebImageDetail(img, ownerNode));
  return row;
}

function renderWebTreeNode(node, depth) {
  const relevantChildren = node.children.filter(subtreeHasWebImages);
  const ownImages = node._images || [];
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `▸ ${node.type} ${node.identifier} ${node.title}`.trim();

  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    relevantChildren.forEach((child) => childrenBox.appendChild(renderWebTreeNode(child, depth + 1)));
    ownImages.forEach((img) => childrenBox.appendChild(renderWebImageRow(img, node, depth + 1)));
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

async function loadWebToc() {
  const content = document.getElementById("web-image-tree-content");
  const res = await fetch("/api/web-toc");
  if (!res.ok) {
    content.textContent = "Not built yet - run src/build_web_toc.py, then reload.";
    return;
  }
  const data = await res.json();
  attachWebImagesToOwners(data.tree, data.images);
  content.innerHTML = "";
  if (subtreeHasWebImages(data.tree)) {
    content.appendChild(renderWebTreeNode(data.tree, 0));
  }
}

document.getElementById("web-image-detail-close").addEventListener("click", () => {
  document.getElementById("web-image-detail").style.display = "none";
});
```

Extend the tab table and wiring (replace the existing `TABS`/`TAB_CONTENT_ID` lines):

```javascript
const TABS = ["toc", "images", "image-tree", "web-images"];
const TAB_CONTENT_ID = {
  toc: "tree", images: "images", "image-tree": "image-tree", "web-images": "web-images",
};
```

Add `loadWebToc()` to `init()`:

```javascript
(async function init() {
  pdfDoc = await pdfjsLib.getDocument("/pdf").promise;
  await renderPage(1);
  await loadToc();
  await loadImages();
  await loadImageTree();
  await loadWebToc();
})();
```

- [ ] **Step 4: Manually verify in the Browser pane**

1. Run `python3 src/build_web_toc.py` (takes a few minutes — fetches ~100 sections).
2. Run `python3 src/serve_mo_toc.py`, open `http://127.0.0.1:8001` in the Browser pane.
3. Confirm the three existing tabs still behave exactly as before (no regression).
4. Click the new "BC Code (Web)" tab; expand a branch known to have images (e.g. Part 9 →
   9.23 Wood-Frame Construction); click an image row; confirm the detail panel shows the
   image, alt text, citation, and a working "View on official site ↗" link that opens the
   live site in a new tab.
5. Click another image; confirm the panel updates (doesn't stack or duplicate).

- [ ] **Step 5: Commit**

```bash
git add src/mo_toc/web/static/index.html src/mo_toc/web/static/style.css src/mo_toc/web/static/viewer.js
git commit -m "feat: add BC Code (Web) Table of Images tab"
```

---

### Task 10: Real-site integration test (`slow`)

**Files:**
- Create: `tests/test_web_toc_integration_real_site.py`
- Modify: `pyproject.toml` — broaden the `slow` marker's description only (its behavior —
  excluded from the default `pytest -q` run — is unchanged).

**Interfaces:**
- Consumes: `HttpxWebSource` (Task 6), `build_tree` (Task 3), `content_url` (Task 2) — no new interfaces produced; this is a smoke test only.

- [ ] **Step 1: Write the test**

```python
# tests/test_web_toc_integration_real_site.py
import pytest

from web_toc.parsing.content_url import content_url
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.tree_builder import build_tree

BASE_URL = "https://dev.buildingcode.gov.bc.ca"
VERSION = "2024"


def _find(node, citation):
    if node.citation == citation:
        return node
    for child in node.children:
        found = _find(child, citation)
        if found is not None:
            return found
    return None


@pytest.mark.slow
def test_navigation_tree_has_two_volumes():
    source = HttpxWebSource(BASE_URL, VERSION)
    root = build_tree(source.fetch_navigation_tree())
    assert len(root.children) == 2


@pytest.mark.slow
def test_front_matter_preface_content_is_fetchable():
    source = HttpxWebSource(BASE_URL, VERSION)
    root = build_tree(source.fetch_navigation_tree())
    preface = _find(root, "nbc.2020.preface")
    assert preface is not None

    url = content_url(preface, VERSION)
    content = source.fetch_content(url)

    assert content is not None
    assert content["id"] == "nbc.2020.preface"
```

- [ ] **Step 2: Run to verify it passes against the real site**

Run: `pytest tests/test_web_toc_integration_real_site.py -v -m slow`
Expected: PASS (2 tests) — makes real HTTP requests to `dev.buildingcode.gov.bc.ca`.

- [ ] **Step 3: Confirm the default run still skips it**

Run: `pytest -q`
Expected: no network activity; the two `slow`-marked tests are skipped (deselected by `-m "not slow"` in `pyproject.toml`).

- [ ] **Step 4: Broaden the `slow` marker's description**

```toml
# pyproject.toml
markers = [
    "slow: exercises the full 1685-page PDF or the real BC Building Code website; skipped unless -m slow is passed",
]
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_toc_integration_real_site.py pyproject.toml
git commit -m "test(web_toc): add real-site slow integration test"
```

---

### Task 11: Update docs (`Readme.md`, `CLAUDE.md`)

**Files:**
- Modify: `Readme.md` — add a "3. BC Building Code (Web) — Table of Images" section, same
  shape as the existing MO Package section (setup, build command, what it produces).
- Modify: `CLAUDE.md` — mention `src/web_toc/`/`src/build_web_toc.py` in the project
  description and folder structure, and extend the Definition-of-Done scope line to include
  the two new paths.

**No tests** — documentation only.

- [ ] **Step 1: Add the new section to `Readme.md`**, after the existing "## 2. MO Package TOC + Image viewer" section and before "## Folder structure":

```markdown
## 3. BC Building Code (Web) — Table of Images (`src/web_toc/`)

Builds a second, independent hierarchical Table of Images — this one sourced from the live
[BC Building Code website](https://dev.buildingcode.gov.bc.ca/?version=2024&date=2024-03-08)
rather than the local PDF, using its own `navigation-tree.json` and per-section content JSON.
Served as a fourth tab in the same viewer (`src/serve_mo_toc.py`); images are hotlinked
directly from the official site rather than mirrored locally.

### Build the index

```bash
python src/build_web_toc.py

# or a different site version
python src/build_web_toc.py --base-url https://dev.buildingcode.gov.bc.ca --version 2024
```

Writes `output/web_toc.json`. Makes ~100 real HTTP requests to the live site and takes a few
minutes; safe to delete and rebuild. Requires no local PDF or credentials.

Then run `python src/serve_mo_toc.py` as usual — the "BC Code (Web)" tab reads this file if
present, and shows a "not built yet" message otherwise.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In the `## Project` section's item 2 (MO Package TOC + Image viewer paragraph), add one
sentence after its existing description:

```markdown
A second, independent index (`src/web_toc/`, `src/build_web_toc.py`) is sourced from the
live BC Building Code website's own navigation tree and content JSON instead of the PDF, and
is served as a fourth tab in the same viewer.
```

In `## Folder structure`, add a bullet after the existing `mo_toc.py`/`check_directory_access.py` line:

```markdown
- `web_toc.py` — the BC Building Code website indexing library (mirrors `mo_toc/`'s
  domain/parsing/output split), fetching from `https://dev.buildingcode.gov.bc.ca` rather
  than reading a local PDF. `build_web_toc.py` is its CLI entry point.
```

In `## Definition of done`, change the scope line from:

```
`src/mo_toc/`, `src/build_mo_toc.py`, `src/serve_mo_toc.py`, and `tests/`
```

to:

```
`src/mo_toc/`, `src/build_mo_toc.py`, `src/serve_mo_toc.py`, `src/web_toc/`,
`src/build_web_toc.py`, and `tests/`
```

- [ ] **Step 3: Commit**

```bash
git add Readme.md CLAUDE.md
git commit -m "docs: document the BC Building Code web Table of Images tab"
```

---

## Final verification (after all tasks)

```bash
ruff check --fix src/mo_toc src/build_mo_toc.py src/serve_mo_toc.py src/web_toc src/build_web_toc.py tests
ruff format src/mo_toc src/build_mo_toc.py src/serve_mo_toc.py src/web_toc src/build_web_toc.py tests
radon cc -s -n B src/mo_toc src/build_mo_toc.py src/serve_mo_toc.py src/web_toc src/build_web_toc.py tests
vulture src/mo_toc src/build_mo_toc.py src/serve_mo_toc.py src/web_toc src/build_web_toc.py tests
pytest -q                    # full suite, network-free, must be all-green
pytest -q -m slow            # both slow suites (real PDF + real website) — run manually, not in CI
```

Plus the manual browser verification from Task 9, Step 4, re-run once more end to end.
