// Pure helpers for the "Table of Contents - Both" tab: matching a PDF-tree
// node to its web counterpart by unified_number, and the geometry for
// drawing a highlight rectangle over the web page rendered in an iframe.
// No DOM access here - see tests/js/both_view.test.mjs.

// A Figure is any image the PDF itself captioned - genuine document
// structure, kept "figure" even if its bbox shape also looks decorative.
// Everything else splits on the same `decorative` flag the PDF tab's own
// declutter toggle uses: a small icon/logo is "image", anything else
// uncaptioned is an inline Equation/Formula crop.
export function classifyImage(img) {
  if (img.caption_kind === "Figure") return "figure";
  return img.decorative ? "image" : "equation";
}

function walkTree(node, into) {
  if (node.unified_number && node.location) into.set(node.unified_number, node.location);
  node.children.forEach((child) => walkTree(child, into));
}

// Both files key every node/image by the same unified_number, so a direct
// lookup replaces the Compare tab's fuzzy title/src matching.
export function collectUnifiedLocations(tree, images) {
  const map = new Map();
  walkTree(tree, map);
  images.forEach((img) => {
    if (img.unified_number && img.location) map.set(img.unified_number, img.location);
  });
  return map;
}

// location.page_file is "web_pages/<citation>.html"; the server serves the
// same saved page at /web-page/<citation>.
export function pageFileRoute(pageFile) {
  const citation = pageFile.replace(/^web_pages\//, "").replace(/\.html$/, "");
  return `/web-page/${encodeURIComponent(citation)}`;
}

// bbox is CSS px from the content panel's own top-left (see layout_join.py),
// so a highlight div appended as that panel's own child can use it as-is -
// no need to locate the panel within the wider page. A zero-size bbox (seen
// in the data for some equation captures) still gets a visible box.
export function minVisibleBox(bbox) {
  return {
    left: bbox.x0,
    top: bbox.y0,
    width: Math.max(bbox.x1 - bbox.x0, 2),
    height: Math.max(bbox.y1 - bbox.y0, 2),
  };
}

// The Text filter's rows. Headings (Volume ... Article, the Appendix chain)
// are the tree's frame and stay whatever the filters say; a Table's own
// Rows/Cells are its content and follow the Table.
const TEXT_TYPES = new Set(["Sentence", "Clause", "Subclause", "Note"]);

export function isShownInBoth(node, filters) {
  if (TEXT_TYPES.has(node.type)) return filters.text;
  if (node.type === "Table") return filters.table;
  return true;
}

// A hidden text row is replaced by whatever it holds that is still shown
// (e.g. a Table lifted out of its Sentence); a hidden Table goes with its
// Rows and Cells.
export function visibleBothChildren(node, filters) {
  return node.children.flatMap((child) => {
    if (isShownInBoth(child, filters)) return [child];
    if (child.type === "Table") return [];
    return visibleBothChildren(child, filters);
  });
}

// citation -> the citation of the row that shows its images: itself when
// shown, else the nearest shown ancestor above it (and above any hidden
// Table it sits in), so a still-ticked Figure never disappears with its row.
export function bothHostCitations(tree, filters) {
  const hosts = new Map();
  const walk = (node, host, insideHiddenTable) => {
    const hiddenTable = insideHiddenTable || (node.type === "Table" && !filters.table);
    const own = !hiddenTable && isShownInBoth(node, filters) ? node.citation : host;
    hosts.set(node.citation, own);
    node.children.forEach((child) => walk(child, own, hiddenTable));
  };
  walk(tree, tree.citation, false);
  return hosts;
}
