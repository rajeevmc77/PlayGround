// Pure helpers for the "Compare" tab: turning a rolled-up match status from
// output/comparison.json into a displayable badge, and building the
// Figures/Tables/Equations/Text/Images checkbox ids for a given tab so the
// Both and Compare tabs' identical filter set isn't spelled out twice.
// No DOM access here - see tests/js/compare_view.test.mjs.

export function statusBadge(matched) {
  if (matched === true) return { glyph: "✓", className: "status-pass" };
  if (matched === false) return { glyph: "✗", className: "status-fail" };
  return { glyph: "", className: "status-unknown" };
}

// "text" stays singular in the id (filter-both-text already shipped this
// way) - every other key pluralizes.
const FILTER_SUFFIXES = {
  figure: "figures",
  table: "tables",
  equation: "equations",
  text: "text",
  image: "images",
};

export function filterIds(prefix) {
  return Object.fromEntries(
    Object.entries(FILTER_SUFFIXES).map(([key, suffix]) => [key, `filter-${prefix}-${suffix}`])
  );
}
