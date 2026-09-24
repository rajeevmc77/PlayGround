// Run with: node --test tests/js/  (also run from pytest by tests/test_viewer_js.py)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  breadcrumbTrail,
  isNavNode,
  navIndent,
  pageOwner,
  scrollTargetId,
  siteNavLabel,
  sitePathKey,
  truncateCrumb,
  viewTarget,
} from "../../src/mo_toc/web/static/web_toc_view.mjs";

const node = (type, citation, title = "", identifier = "") => ({
  type,
  citation,
  title,
  identifier,
  children: [],
});

const volume = node("volume", "vol1", "Volume 1", "1");
const division = node("division", "nbc.divA", "Division A - Compliance, Objectives and Functional Statements", "A");
const part = node("part", "nbc.divA.part1", "Part 1 - Compliance", "1");
const section = node("section", "nbc.divA.part1.sect1", "1.1 General", "1.1");
const subsection = node("subsection", "nbc.divA.part1.sect1.subsect1", "1.1.1 Application of this Code", "1.1.1");
const article = node("article", "nbc.divA.part1.sect1.subsect1.art2", "1.1.1.2 Application to Existing Buildings", "1.1.1.2");
const sentence = node("Sentence", "nbc.divA.part1.sect1.subsect1.art2.sent1", "", "(1)");
const root = node("root", "root", "BC Building Code");
const chain = [root, volume, division, part, section, subsection, article, sentence];
const upTo = (n) => chain.slice(0, chain.indexOf(n) + 1);
const pages = new Set(["nbc.divA.part1", "nbc.divA.part1.sect1"]);

test("siteNavLabel puts a period after section/subsection/article numbers, as the site does", () => {
  assert.equal(siteNavLabel(section), "1.1. General");
  assert.equal(siteNavLabel(subsection), "1.1.1. Application of this Code");
  assert.equal(siteNavLabel(article), "1.1.1.2. Application to Existing Buildings");
});

test("siteNavLabel keeps every other title verbatim", () => {
  assert.equal(siteNavLabel(part), "Part 1 - Compliance");
  assert.equal(siteNavLabel(division), division.title);
  assert.equal(siteNavLabel(volume), "Volume 1");
  assert.equal(siteNavLabel(node("part_appendix", "x", "Notes to Part 1")), "Notes to Part 1");
});

test("siteNavLabel leaves a numbered title alone when it does not start with its number", () => {
  assert.equal(siteNavLabel(node("article", "fm", "Preface", "")), "Preface");
  assert.equal(siteNavLabel(node("section", "s", "General", "1.1")), "General");
});

test("isNavNode is false for body content below article level", () => {
  assert.equal(isNavNode(article), true);
  assert.equal(isNavNode(node("spectables", "t", "Span Tables")), true);
  for (const type of ["Sentence", "Clause", "Subclause", "Table", "Row", "Cell"]) {
    assert.equal(isNavNode(node(type, "x")), false, type);
  }
});

test("navIndent matches the site's own padding per depth", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5].map(navIndent), [0, 32, 48, 64, 80, 96]);
});

test("pageOwner is the deepest node in the chain that has a scraped page", () => {
  assert.equal(pageOwner(upTo(sentence), pages), section);
  assert.equal(pageOwner(upTo(part), pages), part);
});

test("pageOwner is null when nothing in the chain has a page", () => {
  assert.equal(pageOwner(upTo(division), pages), null);
  assert.equal(pageOwner([], pages), null);
});

test("viewTarget is the deepest subsection or article in the chain", () => {
  assert.equal(viewTarget(upTo(subsection)), subsection);
  assert.equal(viewTarget(upTo(article)), article);
  assert.equal(viewTarget(upTo(sentence)), article);
});

test("viewTarget is null for a section, part or anything above", () => {
  assert.equal(viewTarget(upTo(section)), null);
  assert.equal(viewTarget(upTo(part)), null);
});

test("scrollTargetId is the citation of body content, which the site uses as the element id", () => {
  assert.equal(scrollTargetId(sentence), sentence.citation);
  assert.equal(scrollTargetId(node("Table", "a.table1")), "a.table1");
});

test("scrollTargetId is null for navigation nodes", () => {
  assert.equal(scrollTargetId(article), null);
  assert.equal(scrollTargetId(section), null);
});

test("truncateCrumb cuts long titles to 24 characters plus an ellipsis, as the site does", () => {
  assert.equal(truncateCrumb(division.title), "Division A - Compliance,...");
  assert.equal(truncateCrumb("1.1.1. Application of this Code"), "1.1.1. Application of th...");
  assert.equal(truncateCrumb("Part 1 - Compliance"), "Part 1 - Compliance");
  assert.equal(truncateCrumb("x".repeat(24)), "x".repeat(24));
});

test("breadcrumbTrail for a section: Home / ... / Part / Section", () => {
  const trail = breadcrumbTrail(upTo(section));
  assert.deepEqual(
    trail.map((c) => [c.label, c.current, c.navigable]),
    [
      ["Home", false, false],
      ["...", false, false],
      ["Part 1 - Compliance", false, true],
      ["1.1. General", true, false],
    ]
  );
  assert.equal(trail[2].node, part);
  assert.equal(trail[3].full, "1.1. General");
});

test("breadcrumbTrail for a part skips the volume and shows its division unlinked", () => {
  const trail = breadcrumbTrail(upTo(part));
  assert.deepEqual(
    trail.map((c) => [c.label, c.full, c.navigable]),
    [
      ["Home", "Home", false],
      ["Division A - Compliance,...", division.title, false],
      ["Part 1 - Compliance", "Part 1 - Compliance", false],
    ]
  );
});

test("breadcrumbTrail for an article truncates the last two levels", () => {
  const labels = breadcrumbTrail(upTo(article)).map((c) => c.label);
  assert.deepEqual(labels, [
    "Home",
    "...",
    "1.1.1. Application of th...",
    "1.1.1.2. Application to ...",
  ]);
});

test("sitePathKey drops the trailing slash the site's own links carry", () => {
  assert.equal(sitePathKey("/code/nbc.divA/1/1/"), "/code/nbc.divA/1/1");
  assert.equal(sitePathKey("/code/nbc.divA/1/1"), "/code/nbc.divA/1/1");
  assert.equal(sitePathKey("/"), "/");
});

test("breadcrumbTrail of an empty chain is just Home", () => {
  assert.deepEqual(breadcrumbTrail([]).map((c) => c.label), ["Home"]);
});
