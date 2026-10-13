import assert from "node:assert/strict";
import { test } from "node:test";

import {
  filterRows,
  formatMoney,
  formatSeconds,
  hashText,
  imageUrl,
  pdfLink,
  summaryCards,
  usageLines,
  verdictClass,
  verdictOptions,
  webLink,
} from "../../src/mo_toc/web/static/llm_compare_view.mjs";

const ROWS = [
  { key: "B.1.1.Fig1", verdict: "IDENTICAL" },
  { key: "B.1.1.Fig2", verdict: "DIFFERENT" },
  { key: "C.2.Eq1", verdict: "DIFFERENT" },
];

test("filterRows with ALL and no query keeps every row", () => {
  assert.deepEqual(filterRows(ROWS, { verdict: "ALL", query: "" }), ROWS);
});

test("filterRows defaults to everything when given no options", () => {
  assert.deepEqual(filterRows(ROWS), ROWS);
});

test("filterRows keeps only the exact verdict", () => {
  const found = filterRows(ROWS, { verdict: "DIFFERENT", query: "" });
  assert.deepEqual(found.map((r) => r.key), ["B.1.1.Fig2", "C.2.Eq1"]);
});

test("filterRows searches the key case-insensitively as a substring", () => {
  assert.deepEqual(filterRows(ROWS, { verdict: "ALL", query: "eq1" }).map((r) => r.key), ["C.2.Eq1"]);
  assert.deepEqual(filterRows(ROWS, { verdict: "ALL", query: "B.1" }).length, 2);
});

test("filterRows combines verdict and query", () => {
  const found = filterRows(ROWS, { verdict: "DIFFERENT", query: "b.1" });
  assert.deepEqual(found.map((r) => r.key), ["B.1.1.Fig2"]);
});

test("filterRows treats regex characters in the query literally", () => {
  assert.deepEqual(filterRows(ROWS, { verdict: "ALL", query: ".*" }), []);
  assert.deepEqual(filterRows(ROWS, { verdict: "ALL", query: "(" }), []);
});

test("filterRows copes with no rows, a null list and a row without a key", () => {
  assert.deepEqual(filterRows([], { verdict: "DIFFERENT", query: "x" }), []);
  assert.deepEqual(filterRows(null, { verdict: "ALL", query: "" }), []);
  assert.deepEqual(filterRows([{ verdict: "ERROR" }], { verdict: "ALL", query: "a" }), []);
  assert.equal(filterRows([{ verdict: "ERROR" }], { verdict: "ALL", query: "" }).length, 1);
});

test("filterRows ignores surrounding whitespace in the query", () => {
  assert.equal(filterRows(ROWS, { verdict: "ALL", query: "  fig2 " }).length, 1);
});

test("formatSeconds shows seconds under a minute with one decimal", () => {
  assert.equal(formatSeconds(12.34), "12.3s");
  assert.equal(formatSeconds(0), "0.0s");
});

test("formatSeconds shows minutes and zero-padded seconds from a minute up", () => {
  assert.equal(formatSeconds(65), "1m 05s");
  assert.equal(formatSeconds(60), "1m 00s");
  assert.equal(formatSeconds(754), "12m 34s");
});

test("formatSeconds rolls 59.96 s over to a minute instead of showing 60.0s", () => {
  assert.equal(formatSeconds(59.96), "1m 00s");
});

test("formatSeconds shows hours for long runs", () => {
  assert.equal(formatSeconds(3785), "1h 03m 05s");
});

test("formatSeconds shows a dash for missing or invalid values", () => {
  assert.equal(formatSeconds(null), "—");
  assert.equal(formatSeconds(undefined), "—");
  assert.equal(formatSeconds(Number.NaN), "—");
});

test("formatMoney shows five decimals and flags a missing cost", () => {
  assert.equal(formatMoney(0.123456), "$0.12346");
  assert.equal(formatMoney(0), "$0.00000");
  assert.equal(formatMoney(null), "cost unavailable");
  assert.equal(formatMoney(undefined), "cost unavailable");
});

const SUMMARY = {
  total_rows: 1234,
  settled_by_hash: 900,
  judged_by_llm: 300,
  cached_hits: 100,
  calls: 12,
  input_tokens: 123456,
  output_tokens: 789,
  total_tokens: 124245,
  cost: 0.5,
  cumulative_cost: 1.25,
  cumulative_total_tokens: 500000,
  total_seconds: 65,
  scoring_seconds: 5,
  judging_seconds: 60,
  pairs_per_minute: 12.345,
};

function cardMap(summary) {
  return Object.fromEntries(summaryCards(summary).map((c) => [c.label, c.value]));
}

test("summaryCards covers counts, tokens, cost, times and rate", () => {
  const cards = cardMap(SUMMARY);
  assert.equal(cards["images"], "1,234");
  assert.equal(cards["settled by hash"], "900");
  assert.equal(cards["judged by LLM"], "300");
  assert.equal(cards["from cache"], "100");
  assert.equal(cards["LLM calls"], "12");
  assert.equal(cards["input tokens"], "123,456");
  assert.equal(cards["output tokens"], "789");
  assert.equal(cards["total tokens"], "124,245");
  assert.equal(cards["cost this run"], "$0.50000");
  assert.equal(cards["cost, all verdicts"], "$1.25000");
  assert.equal(cards["run time"], "1m 05s");
  assert.equal(cards["scoring time"], "5.0s");
  assert.equal(cards["judging time"], "1m 00s");
  assert.equal(cards["pairs per minute"], "12");
  assert.equal(cardMap({ ...SUMMARY, pairs_per_minute: 2.345 })["pairs per minute"], "2.3");
});

test("summaryCards shows a null cost as cost unavailable", () => {
  const cards = cardMap({ ...SUMMARY, cost: null, cumulative_cost: null });
  assert.equal(cards["cost this run"], "cost unavailable");
  assert.equal(cards["cost, all verdicts"], "cost unavailable");
});

test("summaryCards shows a dash for every value a summary lacks", () => {
  for (const summary of [{}, null, undefined]) {
    const cards = summaryCards(summary);
    assert.ok(cards.length >= 14);
    assert.ok(cards.every((c) => c.value === "—" || c.value === "cost unavailable"));
  }
});

test("summaryCards shows 0 as 0, not a dash", () => {
  assert.equal(cardMap({ ...SUMMARY, cached_hits: 0 })["from cache"], "0");
});

test("summaryCards shows a null rate as a dash and a large rate without decimals", () => {
  assert.equal(cardMap({ ...SUMMARY, pairs_per_minute: null })["pairs per minute"], "—");
  assert.equal(cardMap({ ...SUMMARY, pairs_per_minute: 120.4 })["pairs per minute"], "120");
});

test("verdictClass maps each verdict to a badge colour class", () => {
  assert.equal(verdictClass("IDENTICAL"), "verdict-ok");
  assert.equal(verdictClass("MATCH_PHASH"), "verdict-ok");
  assert.equal(verdictClass("DIFFERENT"), "verdict-bad");
  assert.equal(verdictClass("ERROR"), "verdict-bad");
  assert.equal(verdictClass("SKIPPED"), "verdict-warn");
  assert.equal(verdictClass("WEB_ONLY"), "verdict-info");
});

test("verdictClass falls back for an unknown or missing verdict", () => {
  assert.equal(verdictClass("SOMETHING"), "verdict-none");
  assert.equal(verdictClass(null), "verdict-none");
});

test("imageUrl encodes each path segment but keeps the slashes", () => {
  assert.equal(imageUrl("images/a b#1.png"), "/api/llm-image/images/a%20b%231.png");
  assert.equal(imageUrl("web_images/equations/x?.png"), "/api/llm-image/web_images/equations/x%3F.png");
});

test("imageUrl is null for a missing path", () => {
  assert.equal(imageUrl(null), null);
  assert.equal(imageUrl(undefined), null);
  assert.equal(imageUrl(""), null);
});

test("pdfLink points at the page in the served PDF", () => {
  assert.equal(pdfLink({ pdf_location: { page: 42 } }), "/pdf#page=42");
});

test("pdfLink is null without a location or page", () => {
  assert.equal(pdfLink({ pdf_location: null }), null);
  assert.equal(pdfLink({}), null);
  assert.equal(pdfLink({ pdf_location: {} }), null);
  assert.equal(pdfLink(null), null);
});

test("webLink uses the page file's citation and the anchor", () => {
  const row = { web_location: { page_file: "web_pages/nbc.divB.part4.html" }, web_anchor: "nbc.divB.4.1.2" };
  assert.equal(webLink(row), "/web-page/nbc.divB.part4#nbc.divB.4.1.2");
});

test("webLink omits the fragment when there is no anchor", () => {
  const row = { web_location: { page_file: "web_pages/nbc.divB.part4.html" }, web_anchor: null };
  assert.equal(webLink(row), "/web-page/nbc.divB.part4");
});

test("webLink encodes special characters in the anchor and citation", () => {
  const row = { web_location: { page_file: "web_pages/a b.html" }, web_anchor: "x y#1" };
  assert.equal(webLink(row), "/web-page/a%20b#x%20y%231");
});

test("webLink is null without a location or page file", () => {
  assert.equal(webLink({ web_location: null }), null);
  assert.equal(webLink({ web_location: {} }), null);
  assert.equal(webLink({}), null);
  assert.equal(webLink(null), null);
});

test("verdictOptions lists All first then each verdict with its count", () => {
  assert.deepEqual(verdictOptions({ IDENTICAL: 3, DIFFERENT: 0 }), [
    { value: "ALL", label: "All verdicts" },
    { value: "IDENTICAL", label: "IDENTICAL (3)" },
    { value: "DIFFERENT", label: "DIFFERENT (0)" },
  ]);
});

test("verdictOptions with no counts offers only All", () => {
  assert.deepEqual(verdictOptions(null), [{ value: "ALL", label: "All verdicts" }]);
  assert.deepEqual(verdictOptions({}), [{ value: "ALL", label: "All verdicts" }]);
});

test("hashText shows the hash percentage or nothing", () => {
  assert.equal(hashText({ score: 91.234 }), "hash 91.2%");
  assert.equal(hashText({ score: 0 }), "hash 0.0%");
  assert.equal(hashText({ score: null }), null);
  assert.equal(hashText({}), null);
});

test("usageLines describes tokens, cost and call for a judged row", () => {
  const row = {
    verdict: "DIFFERENT",
    input_tokens: 1500,
    output_tokens: 20,
    cost: 0.00012,
    batch_id: 3,
    call_seconds: 12.34,
    cached: false,
  };
  assert.deepEqual(usageLines(row), ["1,500 in / 20 out", "$0.00012", "batch 3 · 12.3s"]);
});

test("usageLines marks cached rows and rows from an earlier run", () => {
  const row = { verdict: "IDENTICAL", input_tokens: 1, output_tokens: 2, cost: null, batch_id: null, call_seconds: null, cached: true };
  assert.deepEqual(usageLines(row), ["1 in / 2 out", "cost unavailable", "earlier run · cached"]);
});

test("usageLines is empty for rows the LLM did not judge", () => {
  for (const verdict of ["MATCH_PHASH", "SKIPPED", "WEB_ONLY", "ERROR"]) {
    assert.deepEqual(usageLines({ verdict }), []);
  }
});
