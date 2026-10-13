// Pure helpers for the "Image Comparison" tab: filtering, formatting and link
// building for the rows and summary of output/llm_image_compare.json (written
// by src/build_llm_comparison.py). No DOM access here - see
// tests/js/llm_compare_view.test.mjs.

const MISSING = "—";
const COST_UNAVAILABLE = "cost unavailable";

export function filterRows(rows, { verdict = "ALL", query = "" } = {}) {
  const needle = query.trim().toLowerCase();
  return (rows || []).filter((row) => {
    if (verdict !== "ALL" && row.verdict !== verdict) return false;
    return !needle || (row.key || "").toLowerCase().includes(needle);
  });
}

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

export function formatSeconds(seconds) {
  if (!isNumber(seconds)) return MISSING;
  if (Math.round(seconds * 10) / 10 < 60) return `${seconds.toFixed(1)}s`;
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = String(whole % 60).padStart(2, "0");
  if (hours === 0) return `${minutes}m ${secs}s`;
  return `${hours}h ${String(minutes).padStart(2, "0")}m ${secs}s`;
}

export function formatMoney(value) {
  return isNumber(value) ? `$${value.toFixed(5)}` : COST_UNAVAILABLE;
}

const formatCount = (value) => (isNumber(value) ? value.toLocaleString("en-US") : MISSING);

function formatRate(value) {
  if (!isNumber(value)) return MISSING;
  return value >= 10 ? value.toFixed(0) : value.toFixed(1);
}

export function summaryCards(summary) {
  const s = summary || {};
  return [
    { label: "images", value: formatCount(s.total_rows) },
    { label: "settled by hash", value: formatCount(s.settled_by_hash) },
    { label: "judged by LLM", value: formatCount(s.judged_by_llm) },
    { label: "from cache", value: formatCount(s.cached_hits) },
    { label: "LLM calls", value: formatCount(s.calls) },
    { label: "input tokens", value: formatCount(s.input_tokens) },
    { label: "output tokens", value: formatCount(s.output_tokens) },
    { label: "total tokens", value: formatCount(s.total_tokens) },
    { label: "cost this run", value: formatMoney(s.cost) },
    { label: "cost, all verdicts", value: formatMoney(s.cumulative_cost) },
    { label: "run time", value: formatSeconds(s.total_seconds) },
    { label: "scoring time", value: formatSeconds(s.scoring_seconds) },
    { label: "judging time", value: formatSeconds(s.judging_seconds) },
    { label: "pairs per minute", value: formatRate(s.pairs_per_minute) },
  ];
}

const VERDICT_CLASSES = {
  MATCH_PHASH: "verdict-ok",
  IDENTICAL: "verdict-ok",
  DIFFERENT: "verdict-bad",
  ERROR: "verdict-bad",
  SKIPPED: "verdict-warn",
  WEB_ONLY: "verdict-info",
};

export function verdictClass(verdict) {
  return VERDICT_CLASSES[verdict] || "verdict-none";
}

export function verdictOptions(counts) {
  const all = { value: "ALL", label: "All verdicts" };
  const each = Object.entries(counts || {}).map(([verdict, n]) => ({
    value: verdict,
    label: `${verdict} (${n})`,
  }));
  return [all, ...each];
}

export function imageUrl(path) {
  if (!path) return null;
  return `/api/llm-image/${path.split("/").map(encodeURIComponent).join("/")}`;
}

export function pdfLink(row) {
  const page = row?.pdf_location?.page;
  return isNumber(page) ? `/pdf#page=${page}` : null;
}

export function webLink(row) {
  const pageFile = row?.web_location?.page_file;
  if (!pageFile) return null;
  const citation = pageFile.split("/").pop().replace(/\.html$/, "");
  const anchor = row.web_anchor ? `#${encodeURIComponent(row.web_anchor)}` : "";
  return `/web-page/${encodeURIComponent(citation)}${anchor}`;
}

export function hashText(row) {
  return isNumber(row?.score) ? `hash ${row.score.toFixed(1)}%` : null;
}

const JUDGED = new Set(["IDENTICAL", "DIFFERENT"]);

function callNote(row) {
  const call = row.batch_id === null || row.batch_id === undefined ? "earlier run" : `batch ${row.batch_id}`;
  const parts = [call];
  if (isNumber(row.call_seconds)) parts.push(formatSeconds(row.call_seconds));
  if (row.cached) parts.push("cached");
  return parts.join(" · ");
}

export function usageLines(row) {
  if (!JUDGED.has(row?.verdict)) return [];
  return [
    `${formatCount(row.input_tokens)} in / ${formatCount(row.output_tokens)} out`,
    formatMoney(row.cost),
    callNote(row),
  ];
}
