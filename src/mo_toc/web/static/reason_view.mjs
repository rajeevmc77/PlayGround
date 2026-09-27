// What the "Why it differs" box shows for a selected item, from its status
// and its entry in comparison.json's `reasons` (src/comparison/reasons.py).
// Each row is one stretch that differs: [before, changed, after] on each side.
// No DOM access here - see tests/js/reason_view.test.mjs.

const SENTENCES = {
  no_web: "No matching item on the website",
  pdf_empty: "The PDF has no text here; the website does",
  web_empty: "The website has no text here; the PDF does",
  image_inside: "The text matches; an image it holds differs",
  image_differs: "The image differs from the website's",
  no_web_image: "No matching image on the website",
};

function textTitle(category) {
  return category === "Mixed" ? "Text differs in several ways" : `Text differs: ${category.toLowerCase()}`;
}

function remainingNote(reason) {
  const hidden = (reason.edit_count || 0) - (reason.edits || []).length;
  if (hidden <= 0) return "";
  return `${hidden} more difference${hidden === 1 ? "" : "s"} not shown.`;
}

function textRows(reason) {
  return reason.edits.map((edit) => ({ label: edit.category, pdf: edit.pdf, web: edit.web }));
}

function emphasisRows(reason) {
  return reason.edits.map((edit) => ({
    label: `PDF ${edit.pdf_style}, website ${edit.web_style}`,
    pdf: edit.pdf,
    web: edit.web,
  }));
}

// status: the item's ✓/✗ (true/false; undefined if it wasn't compared).
// isContainer: the item has children, whose own reasons explain its ✗.
export function reasonView(status, reason, isContainer) {
  if (status !== false) return null;
  if (!reason) {
    if (isContainer) return { title: "Something inside differs", note: "Open it and look for the items marked ✗.", rows: [] };
    return { title: "Differs from the website", note: "", rows: [] };
  }
  if (reason.kind === "text") return { title: textTitle(reason.category), note: remainingNote(reason), rows: textRows(reason) };
  if (reason.kind === "emphasis") {
    return { title: "Same words, different bold/italic", note: remainingNote(reason), rows: emphasisRows(reason) };
  }
  return { title: SENTENCES[reason.kind] || "Differs from the website", note: "", rows: [] };
}
