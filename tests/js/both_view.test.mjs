// Run with: node --test tests/js/  (also run from pytest by tests/test_viewer_js.py)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  classifyImage,
  collectUnifiedLocations,
  fitScale,
  minVisibleBox,
  pageFileRoute,
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

test("fitScale: the factor that makes content of nativeWidth exactly fill containerWidth", () => {
  assert.equal(fitScale(750, 1500), 0.5);
  assert.equal(fitScale(3000, 1500), 2);
});

test("fitScale: falls back to 1 (native size) when the container hasn't laid out yet", () => {
  assert.equal(fitScale(0, 1500), 1);
  assert.equal(fitScale(-5, 1500), 1);
});
