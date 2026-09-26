import assert from "node:assert/strict";
import { test } from "node:test";

import { filterIds, statusBadge } from "../../src/mo_toc/web/static/compare_view.mjs";

test("statusBadge renders a green check for a passing match", () => {
  const badge = statusBadge(true);
  assert.equal(badge.glyph, "✓");
  assert.equal(badge.className, "status-pass");
});

test("statusBadge renders a red cross for a failing match", () => {
  const badge = statusBadge(false);
  assert.equal(badge.glyph, "✗");
  assert.equal(badge.className, "status-fail");
});

test("statusBadge renders nothing for a node with no comparison data", () => {
  const badge = statusBadge(undefined);
  assert.equal(badge.glyph, "");
  assert.equal(badge.className, "status-unknown");
});

test("filterIds builds the per-tab checkbox id for every filter key", () => {
  assert.deepEqual(filterIds("compare"), {
    figure: "filter-compare-figures",
    table: "filter-compare-tables",
    equation: "filter-compare-equations",
    text: "filter-compare-text",
    image: "filter-compare-images",
  });
});

test("filterIds uses a different prefix for a different tab", () => {
  assert.equal(filterIds("both").figure, "filter-both-figures");
});
