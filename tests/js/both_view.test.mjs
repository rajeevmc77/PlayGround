// Run with: node --test tests/js/  (also run from pytest by tests/test_viewer_js.py)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  bothHostCitations,
  classifyImage,
  collectUnifiedLocations,
  isShownInBoth,
  minVisibleBox,
  pageFileRoute,
  visibleBothChildren,
} from "../../src/mo_toc/web/static/both_view.mjs";

test("classifyImage: a captioned Figure is 'figure' even if it happens to be decorative-shaped", () => {
  assert.equal(classifyImage({ caption_kind: "Figure", decorative: false }), "figure");
  assert.equal(classifyImage({ caption_kind: "Figure", decorative: true }), "figure");
});

test("classifyImage: an uncaptioned decorative image is 'image'", () => {
  assert.equal(classifyImage({ caption_kind: null, decorative: true }), "image");
});

test("classifyImage: an uncaptioned non-decorative image is 'equation'", () => {
  assert.equal(classifyImage({ caption_kind: null, decorative: false }), "equation");
});

const node = (type, unified_number, location, children = []) => ({
  type,
  unified_number,
  location,
  children,
});

const LOC = { page_file: "web_pages/nbc.divA.part1.html", xpath: "/html/body", bbox: { x0: 1, y0: 2, x1: 3, y1: 4 } };

test("collectUnifiedLocations: keys tree nodes by unified_number, skips ones with no key or no location", () => {
  const tree = node("root", "", null, [
    node("part", "A.1", LOC, [node("section", "A.1.1", LOC), node("section", "", LOC)]),
    node("part", "A.2", null),
  ]);
  const map = collectUnifiedLocations(tree, []);
  assert.deepEqual([...map.keys()].sort(), ["A.1", "A.1.1"]);
  assert.equal(map.get("A.1"), LOC);
});

test("collectUnifiedLocations: also indexes images by unified_number", () => {
  const tree = node("root", "", null, []);
  const images = [
    { unified_number: "A.1.Fig1", location: LOC },
    { unified_number: "", location: LOC },
    { unified_number: "A.1.Fig2", location: null },
  ];
  const map = collectUnifiedLocations(tree, images);
  assert.deepEqual([...map.keys()], ["A.1.Fig1"]);
});

test("pageFileRoute: turns a web_pages/<citation>.html path into the /web-page/<citation> route", () => {
  assert.equal(pageFileRoute("web_pages/nbc.divA.part1.html"), "/web-page/nbc.divA.part1");
});

test("pageFileRoute: URL-encodes citation characters a raw path can't carry, e.g. a space", () => {
  assert.equal(
    pageFileRoute("web_pages/nbc.divB.part9 (draft).html"),
    "/web-page/nbc.divB.part9%20(draft)"
  );
});

test("minVisibleBox: bbox is CSS px from the content panel's own top-left, so the box uses it directly", () => {
  const box = minVisibleBox({ x0: 10, y0: 20, x1: 110, y1: 40 });
  assert.deepEqual(box, { left: 10, top: 20, width: 100, height: 20 });
});

test("minVisibleBox: enforces a minimum visible size for a zero-height bbox", () => {
  const box = minVisibleBox({ x0: 10, y0: 20, x1: 10, y1: 20 });
  assert.equal(box.width >= 2, true);
  assert.equal(box.height >= 2, true);
});

const pdfNode = (type, citation, children = []) => ({ type, citation, children });
const ALL_ON = { text: true, table: true };

// Article > Sentence > [Clause > [Subclause], Table > [Row > [Cell]]]
function sampleArticle() {
  return pdfNode("Article", "art", [
    pdfNode("Sentence", "sent", [
      pdfNode("Clause", "clause", [pdfNode("Subclause", "sub")]),
      pdfNode("Table", "table", [pdfNode("Row", "row", [pdfNode("Cell", "cell")])]),
    ]),
    pdfNode("Note", "note"),
  ]);
}

const citations = (nodes) => nodes.map((n) => n.citation);

test("isShownInBoth: headings are always shown, whatever the filters", () => {
  const off = { text: false, table: false };
  ["Volume", "Division", "Part", "Section", "Subsection", "Article", "AppendixArticle"].forEach((type) =>
    assert.equal(isShownInBoth({ type }, off), true, type)
  );
});

test("isShownInBoth: Sentence/Clause/Subclause/Note follow the Text filter", () => {
  ["Sentence", "Clause", "Subclause", "Note"].forEach((type) => {
    assert.equal(isShownInBoth({ type }, { text: true, table: true }), true, type);
    assert.equal(isShownInBoth({ type }, { text: false, table: true }), false, type);
  });
});

test("isShownInBoth: a Table follows the Tables filter; its Rows/Cells are its own content", () => {
  assert.equal(isShownInBoth({ type: "Table" }, { text: true, table: false }), false);
  assert.equal(isShownInBoth({ type: "Row" }, { text: false, table: false }), true);
  assert.equal(isShownInBoth({ type: "Cell" }, { text: false, table: false }), true);
});

test("visibleBothChildren: all filters on keeps the tree as it is", () => {
  const article = sampleArticle();
  assert.deepEqual(citations(visibleBothChildren(article, ALL_ON)), ["sent", "note"]);
  assert.deepEqual(citations(visibleBothChildren(article.children[0], ALL_ON)), ["clause", "table"]);
});

test("visibleBothChildren: Text off lifts a Table out of its hidden Sentence", () => {
  const article = sampleArticle();
  assert.deepEqual(citations(visibleBothChildren(article, { text: false, table: true })), ["table"]);
});

test("visibleBothChildren: Tables off drops the Table with its Rows and Cells", () => {
  const sentence = sampleArticle().children[0];
  assert.deepEqual(citations(visibleBothChildren(sentence, { text: true, table: false })), ["clause"]);
});

test("visibleBothChildren: everything off leaves only headings", () => {
  const part = pdfNode("Part", "part", [pdfNode("Section", "sect", [sampleArticle()])]);
  const off = { text: false, table: false };
  assert.deepEqual(citations(visibleBothChildren(part, off)), ["sect"]);
  assert.deepEqual(citations(visibleBothChildren(sampleArticle(), off)), []);
});

test("visibleBothChildren: a leaf has no children", () => {
  assert.deepEqual(visibleBothChildren(pdfNode("Subclause", "sub"), ALL_ON), []);
});

test("bothHostCitations: a shown node hosts its own images", () => {
  const hosts = bothHostCitations(sampleArticle(), ALL_ON);
  assert.equal(hosts.get("sub"), "sub");
  assert.equal(hosts.get("cell"), "cell");
});

test("bothHostCitations: a hidden text node's images move to its nearest shown ancestor", () => {
  const hosts = bothHostCitations(sampleArticle(), { text: false, table: true });
  assert.equal(hosts.get("clause"), "art");
  assert.equal(hosts.get("sub"), "art");
  assert.equal(hosts.get("note"), "art");
  assert.equal(hosts.get("table"), "table");
});

test("bothHostCitations: images inside a hidden Table move above the Table", () => {
  const hosts = bothHostCitations(sampleArticle(), { text: true, table: false });
  assert.equal(hosts.get("table"), "sent");
  assert.equal(hosts.get("cell"), "sent");
});

test("bothHostCitations: everything off hosts every image on the heading above it", () => {
  const hosts = bothHostCitations(sampleArticle(), { text: false, table: false });
  ["art", "sent", "clause", "sub", "table", "row", "cell", "note"].forEach((c) =>
    assert.equal(hosts.get(c), "art", c)
  );
});
