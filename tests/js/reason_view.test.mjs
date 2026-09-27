// Run with: node --test tests/js/  (also run from pytest by tests/test_viewer_js.py)
import { test } from "node:test";
import assert from "node:assert/strict";

import { reasonView } from "../../src/mo_toc/web/static/reason_view.mjs";

const text = {
  kind: "text",
  category: "Punctuation",
  edit_count: 1,
  edits: [{ category: "Punctuation", pdf: ["", "reserved", ","], web: ["", "reserved", ""] }],
};

test("reasonView: a passed or unknown item shows nothing", () => {
  assert.equal(reasonView(true, undefined, false), null);
  assert.equal(reasonView(undefined, undefined, false), null);
});

test("reasonView: a text difference names its kind and each stretch on both sides", () => {
  const view = reasonView(false, text, false);
  assert.equal(view.title, "Text differs: punctuation");
  assert.deepEqual(view.rows, [
    { label: "Punctuation", pdf: ["", "reserved", ","], web: ["", "reserved", ""] },
  ]);
  assert.equal(view.note, "");
});

test("reasonView: more differences than listed are counted in the note", () => {
  const view = reasonView(false, { ...text, category: "Mixed", edit_count: 5 }, false);
  assert.equal(view.title, "Text differs in several ways");
  assert.equal(view.note, "4 more differences not shown.");
});

test("reasonView: bold/italic differences label each word with both styles", () => {
  const emphasis = {
    kind: "emphasis",
    edit_count: 1,
    edits: [{ pdf: ["", "General", ""], web: ["", "General", ""], pdf_style: "bold", web_style: "plain" }],
  };
  const view = reasonView(false, emphasis, false);
  assert.equal(view.title, "Same words, different bold/italic");
  assert.equal(view.rows[0].label, "PDF bold, website plain");
});

test("reasonView: kinds without text stretches get a sentence", () => {
  assert.equal(reasonView(false, { kind: "no_web" }, false).title, "No matching item on the website");
  assert.equal(reasonView(false, { kind: "no_web_image" }, false).title, "No matching image on the website");
  assert.equal(reasonView(false, { kind: "image_differs" }, false).title, "The image differs from the website's");
  assert.deepEqual(reasonView(false, { kind: "pdf_empty" }, false).rows, []);
});

test("reasonView: a failed container points to the items inside it", () => {
  const view = reasonView(false, undefined, true);
  assert.equal(view.title, "Something inside differs");
  assert.equal(view.note, "Open it and look for the items marked ✗.");
});
