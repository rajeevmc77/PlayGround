import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let currentPage = 1;
let tocVolume = null;
let allImages = null;
let webTocTree = null;

function formatNodeLabel(node) {
  const text = node.title || node.content;
  return [node.unified_number, node.type, node.identifier, text].filter(Boolean).join(" ");
}

async function loadToc() {
  const res = await fetch("/api/toc");
  tocVolume = await res.json();
}

async function loadAllImages() {
  const res = await fetch("/api/images");
  allImages = await res.json();
}

// A Figure is any image the PDF itself captioned "Figure ...". An uncaptioned,
// non-decorative image is an inline Equation/Formula crop (see
// mo_toc.domain.image_classification.is_decorative for what "decorative"
// excludes) - the building code never leaves a genuine Figure uncaptioned.
function isFigure(img) {
  return img.caption_kind === "Figure";
}

function isEquation(img) {
  return !img.caption_kind && !img.decorative;
}

function clearAttachedTocImages(node) {
  delete node._tocImages;
  node.children.forEach(clearAttachedTocImages);
}

// A Table node is genuine document structure (attached in place by
// mo_toc.parsing.table_extractor.attach_tables), not an overlay row like a
// Figure/Equation - it counts toward "keep this branch" whenever the Tables
// filter is on, independent of whether it happens to own any images.
function subtreeHasTocContent(node, showTables) {
  if (node._tocImages && node._tocImages.length > 0) return true;
  if (showTables && node.type === "Table") return true;
  return node.children.some((child) => subtreeHasTocContent(child, showTables));
}

function attachTocImages(showFigures, showEquations) {
  clearAttachedTocImages(tocVolume);
  const citationMap = buildCitationMap(tocVolume, {});
  allImages.forEach((img, index) => {
    const matches = (showFigures && isFigure(img)) || (showEquations && isEquation(img));
    if (!matches) return;
    const owner = citationMap[img.owner_citation];
    if (!owner) return;
    if (!owner._tocImages) owner._tocImages = [];
    owner._tocImages.push({ img, index });
  });
}

function renderTocNode(node, depth, pruning, showTables) {
  // Once we're rendering a matched Table's own Row/Cell children, they're
  // its content, not independent branches to filter - none of them are
  // themselves a Table or image owner, so pruning would hide every row of
  // a table the user just chose to expand.
  const childPruning = pruning && node.type !== "Table";
  const relevantChildren = childPruning
    ? node.children.filter((child) => subtreeHasTocContent(child, showTables))
    : node.children;
  const ownImages = node._tocImages || [];
  const hasChildren = relevantChildren.length > 0 || ownImages.length > 0;
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `${hasChildren ? "▸ " : ""}${formatNodeLabel(node)}`.trim();
  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    goToLocation(node.page, node.bbox);
    if (!hasChildren) return;
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    relevantChildren.forEach((child) => {
      childrenBox.appendChild(renderTocNode(child, depth + 1, childPruning, showTables));
    });
    ownImages.forEach(({ img, index }) => {
      childrenBox.appendChild(renderImageRow(img, index, depth + 1));
    });
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

function renderTocTree() {
  const showFigures = document.getElementById("filter-figures").checked;
  const showEquations = document.getElementById("filter-equations").checked;
  const showTables = document.getElementById("filter-tables").checked;
  const pruning = showFigures || showEquations || showTables;
  if (showFigures || showEquations) {
    attachTocImages(showFigures, showEquations);
  } else {
    clearAttachedTocImages(tocVolume);
  }
  const content = document.getElementById("tree-content");
  content.innerHTML = "";
  content.appendChild(renderTocNode(tocVolume, 0, pruning, showTables));
}

function isHiddenByDeclutter(img, declutterOn) {
  // `decorative` is computed server-side (mo_toc.domain.image_classification
  // .is_decorative) from the image's bbox - a near-square AND small-area
  // shape, the kind a logo/icon leaves. A wide-but-short single-line formula
  // is neither, so it stays visible even with declutter on.
  return declutterOn && img.decorative;
}

function imageLabel(img) {
  if (img.caption_identifier) return `${img.caption_kind} ${img.caption_identifier}`;
  return `p.${img.page} (${img.width}x${img.height})`;
}

function renderImageRow(img, index, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="/api/image/${index}"> ${imageLabel(img)}`;
  row.addEventListener("click", () => goToLocation(img.page, img.bbox));
  return row;
}

function buildCitationMap(node, map) {
  map[node.citation] = node;
  node.children.forEach((child) => buildCitationMap(child, map));
  return map;
}

function clearAttachedImages(node) {
  delete node._images;
  node.children.forEach(clearAttachedImages);
}

function attachImagesToOwners(declutterOn) {
  clearAttachedImages(tocVolume);
  const citationMap = buildCitationMap(tocVolume, {});
  allImages.forEach((img, index) => {
    if (isHiddenByDeclutter(img, declutterOn)) return;
    const owner = citationMap[img.owner_citation];
    if (!owner) return;
    if (!owner._images) owner._images = [];
    owner._images.push({ img, index });
  });
}

function subtreeHasImages(node) {
  if (node._images && node._images.length > 0) return true;
  return node.children.some(subtreeHasImages);
}

function webImageUrl(img) {
  if (img.local_path) return `/api/web-image/${encodeURIComponent(img.id)}/thumbnail`;
  return `https://dev.buildingcode.gov.bc.ca/${img.src}.jpg`;
}

function buildWebCitationMap(node, map) {
  map[node.citation] = node;
  node.children.forEach((child) => buildWebCitationMap(child, map));
  return map;
}

function clearAttachedWebImages(node) {
  delete node._images;
  node.children.forEach(clearAttachedWebImages);
}

function attachWebImagesToOwners(tree, images) {
  clearAttachedWebImages(tree);
  const citationMap = buildWebCitationMap(tree, {});
  images.forEach((img) => {
    const owner = citationMap[img.owner_citation];
    if (!owner) return;
    if (!owner._images) owner._images = [];
    owner._images.push(img);
  });
}

function showWebImageDetail(img, ownerNode) {
  document.getElementById("web-image-detail-img").src = webImageUrl(img);
  document.getElementById("web-image-detail-alt").textContent = img.alt_text || "(no description)";
  document.getElementById("web-image-detail-citation").textContent = formatNodeLabel(ownerNode);
  document.getElementById("web-image-detail-link").href =
    `https://dev.buildingcode.gov.bc.ca${ownerNode.path}?version=2024&date=2024-03-08`;
  document.getElementById("web-image-detail").style.display = "block";
}

function renderWebImageRow(img, ownerNode, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="${webImageUrl(img)}" loading="lazy"> ${img.alt_text || "(no description)"}`;
  row.addEventListener("click", () => showWebImageDetail(img, ownerNode));
  return row;
}

// The web TOC has no Figure/Equation split like the pdf's caption_kind - every
// web image is just "Figures" here. "Tables" are real structural content:
// either a "Table" node extracted from a section's own content (the web
// equivalent of the pdf's Table node, with the same Table -> Row -> Cell
// shape), or one of the site's own "spectables" special-tables index pages.
// "Body Text" is a "Sentence" node (the web equivalent of the pdf's Sentence
// node, with the same Sentence -> Clause -> Subclause shape). None of these
// is an image overlay, so all three count toward "keep this branch" on
// their own.
function subtreeHasWebTocContent(node, showFigures, showTables, showBody) {
  if (showFigures && node._images && node._images.length > 0) return true;
  if (showTables && (node.type === "Table" || node.type === "spectables")) return true;
  if (showBody && node.type === "Sentence") return true;
  return node.children.some((child) =>
    subtreeHasWebTocContent(child, showFigures, showTables, showBody)
  );
}

function renderTocWebNode(node, depth, pruning, showFigures, showTables, showBody, inheritedPath) {
  // Once we're rendering a matched Table's or Sentence's own children,
  // they're its content, not independent branches to filter - a Row/Cell or
  // Clause/Subclause is never itself a Table/spectables/Sentence or image
  // owner, so pruning would hide every row/clause of a match the user just
  // chose to expand.
  const childPruning = pruning && node.type !== "Table" && node.type !== "Sentence";
  const relevantChildren = childPruning
    ? node.children.filter((child) =>
        subtreeHasWebTocContent(child, showFigures, showTables, showBody)
      )
    : node.children;
  const ownImages = showFigures ? node._images || [] : [];
  const hasChildren = relevantChildren.length > 0 || ownImages.length > 0;
  const nodePath = node.path || inheritedPath;
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `${hasChildren ? "▸ " : ""}${formatNodeLabel(node)}`.trim();

  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    showWebContentDetail(node, nodePath);
    if (!hasChildren) return;
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    relevantChildren.forEach((child) => {
      childrenBox.appendChild(
        renderTocWebNode(child, depth + 1, childPruning, showFigures, showTables, showBody, nodePath)
      );
    });
    ownImages.forEach((img) => childrenBox.appendChild(renderWebImageRow(img, node, depth + 1)));
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

function renderTocWebTree() {
  const showFigures = document.getElementById("filter-web-figures").checked;
  const showTables = document.getElementById("filter-web-tables").checked;
  const showBody = document.getElementById("filter-web-body").checked;
  const pruning = showFigures || showTables || showBody;
  const content = document.getElementById("tree-web-content");
  content.innerHTML = "";
  content.appendChild(
    renderTocWebNode(webTocTree, 0, pruning, showFigures, showTables, showBody, webTocTree.path)
  );
}

// Structural levels above a Section have no single reading page on the live
// site either - navigating to a Part/Division/Volume there shows "Select a
// section to start reading" plus a list of its children, not their full
// inlined content (confirmed by loading one live). Rendering full content
// for these would mean dumping an entire Division's text into the DOM at
// once, so they get the same shallow child-list treatment here.
const WEB_CONTENT_SUMMARY_TYPES = new Set(["root", "volume", "division", "part", "index", "conversions"]);

// Raw extracted text/cell content carries three kinds of site-specific
// markup. Bold/italic aren't decorative here - the live site uses them to
// distinguish two different semantic things (a defined term vs. a plain
// cross-reference), confirmed by reading its own computed styles:
//   <bold>...</bold>            - wraps its inner (possibly marked-up) text;
//                                 renders as font-weight 700, no color change
//   [REF:term:<code>:<label>]   - a defined term ("glossary-term" span):
//                                 italic, #1a5a96, weight 400
//   [REF:internal:<citation>:(long|short)] - a cross-reference
//                                 ("cross-reference-link" button), labelled
//                                 e.g. "Sentence 3.1.3.1.(1)": NOT italic,
//                                 #255a90, weight 400
// Neither glossary popovers nor working cross-reference links are worth
// building for this internal viewer, but the bold/italic distinction itself
// is kept (see .web-content-term / .web-content-xref in style.css).
const MARKUP_RE =
  /<bold>([\s\S]*?)<\/bold>|\[REF:term:[^:]+:([^\]]+)\]|\[REF:internal:([^:\]]+):(?:long|short)\]/g;

let webCitationIndex = null;

function resolveInternalRefLabel(citation) {
  if (!webCitationIndex) webCitationIndex = buildWebCitationMap(webTocTree, {});
  const target = webCitationIndex[citation];
  if (!target) return citation;
  return [target.type, target.unified_number].filter(Boolean).join(" ");
}

function appendMarkedUpText(parent, text) {
  // text.matchAll() (not MARKUP_RE.exec() in a loop) because this function
  // recurses into a <bold> match's own inner text: a shared regex object's
  // .lastIndex is mutated by .exec(), so a recursive call would stomp on the
  // outer loop's iteration position and hang the page in an infinite loop.
  // matchAll's iterator carries its own independent position instead.
  let lastIndex = 0;
  for (const match of text.matchAll(MARKUP_RE)) {
    if (match.index > lastIndex) {
      parent.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    }
    const [, boldInner, termLabel, internalCitation] = match;
    if (boldInner !== undefined) {
      const strong = document.createElement("strong");
      appendMarkedUpText(strong, boldInner);
      parent.appendChild(strong);
    } else if (termLabel !== undefined) {
      const em = document.createElement("em");
      em.className = "web-content-term";
      em.textContent = termLabel;
      parent.appendChild(em);
    } else {
      const span = document.createElement("span");
      span.className = "web-content-xref";
      span.textContent = resolveInternalRefLabel(internalCitation);
      parent.appendChild(span);
    }
    lastIndex = match.index + match[0].length;
  }
  parent.appendChild(document.createTextNode(text.slice(lastIndex)));
}

function renderWebContentImage(img) {
  const figure = document.createElement("figure");
  figure.className = "web-content-image";
  const el = document.createElement("img");
  el.src = webImageUrl(img);
  el.loading = "lazy";
  figure.appendChild(el);
  const caption = document.createElement("figcaption");
  caption.textContent = img.alt_text || "(no description)";
  figure.appendChild(caption);
  return figure;
}

function renderWebContentTable(node) {
  const wrapper = document.createElement("div");
  if (node.title) {
    const title = document.createElement("div");
    title.className = "web-content-table-title";
    title.textContent = node.title;
    wrapper.appendChild(title);
  }
  const table = document.createElement("table");
  table.className = "web-content-table";
  // The extracted Table -> Row shape concatenates header_rows then body_rows
  // with no marker of which is which (table_extractor.py); every real table
  // seen has exactly one header row, so the first row is rendered as the
  // header (<th>, bold, shaded) the way the live site's table-block__header-
  // cell renders it, and the rest as plain data cells.
  node.children.forEach((row, rowIndex) => {
    const tr = document.createElement("tr");
    const cellTag = rowIndex === 0 ? "th" : "td";
    row.children.forEach((cell) => {
      const cellEl = document.createElement(cellTag);
      appendMarkedUpText(cellEl, cell.content);
      tr.appendChild(cellEl);
    });
    table.appendChild(tr);
  });
  wrapper.appendChild(table);
  return wrapper;
}

// Matches the live site's sentenceNumber/clauseNumber/subclauseNumber spans:
// only the sentence number is bold, and each level has its own text color.
const NUMBER_LABEL_CLASS = {
  Sentence: "web-content-sentence-number",
  Clause: "web-content-clause-number",
  Subclause: "web-content-subclause-number",
};

function renderWebContentTextItem(node, tag) {
  const el = document.createElement(tag);
  el.className = "web-content-item";
  const label = document.createElement("span");
  label.className = NUMBER_LABEL_CLASS[node.type] || "";
  label.textContent = `${node.identifier} `;
  el.appendChild(label);
  appendMarkedUpText(el, node.content);
  return el;
}

function renderWebContentSummary(node) {
  const container = document.createElement("div");
  container.className = "web-content-node";
  const hint = document.createElement("p");
  hint.className = "compare-placeholder";
  hint.textContent = "No single reading page at this level - pick an item below, or a node further down the left tree.";
  container.appendChild(hint);
  const list = document.createElement("ul");
  list.className = "web-content-summary-list";
  node.children.forEach((child) => {
    const li = document.createElement("li");
    li.textContent = formatNodeLabel(child);
    list.appendChild(li);
  });
  container.appendChild(list);
  return container;
}

// Matches the live site's partTitle/sectionTitle/subsectionHeading/
// articleHeading elements (h1/h2/h3/h4 respectively, each with its own
// font-size - subsectionHeading is actually larger than sectionTitle there).
// Types with no page of their own (part_appendix, division_appendix,
// spectables, front-matter article) fall back to the article level.
const HEADING_TAG = { part: "h1", section: "h2", subsection: "h3", article: "h4" };

function renderWebContentNode(node) {
  if (WEB_CONTENT_SUMMARY_TYPES.has(node.type)) return renderWebContentSummary(node);

  const container = document.createElement("div");
  container.className = "web-content-node";

  if (node.type === "Table") {
    container.appendChild(renderWebContentTable(node));
  } else if (node.type === "Sentence" || node.type === "Clause" || node.type === "Subclause") {
    container.appendChild(renderWebContentTextItem(node, "p"));
    node.children.forEach((child) => container.appendChild(renderWebContentNode(child)));
  } else {
    if (node.title) {
      const heading = document.createElement(HEADING_TAG[node.type] || "h4");
      heading.textContent = [node.unified_number, node.title].filter(Boolean).join(" ");
      container.appendChild(heading);
    }
    node.children.forEach((child) => container.appendChild(renderWebContentNode(child)));
  }

  (node._images || []).forEach((img) => container.appendChild(renderWebContentImage(img)));
  return container;
}

function showWebContentDetail(node, path) {
  document.getElementById("web-content-header").textContent = formatNodeLabel(node);
  const body = document.getElementById("web-content-body");
  body.classList.remove("compare-placeholder");
  body.innerHTML = "";
  body.appendChild(renderWebContentNode(node));
  const link = document.getElementById("web-content-link");
  if (path) {
    link.href = `https://dev.buildingcode.gov.bc.ca${path}?version=2024&date=2024-03-08`;
    link.style.display = "inline-block";
  } else {
    link.style.display = "none";
  }
}

async function loadWebToc() {
  const content = document.getElementById("tree-web-content");
  const res = await fetch("/api/web-toc");
  if (!res.ok) {
    content.textContent = "Not built yet - run src/build_web_toc.py, then reload.";
    return;
  }
  const data = await res.json();
  webTocTree = data.tree;
  attachWebImagesToOwners(webTocTree, data.images);
  renderTocWebTree();
}

document.getElementById("web-image-detail-close").addEventListener("click", () => {
  document.getElementById("web-image-detail").style.display = "none";
});

let compareWebImages = [];

function normalizeForMatch(value) {
  return (value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function findMatchingWebImage(pdfImg, webImages) {
  const identifierNeedle = normalizeForMatch(pdfImg.caption_identifier);
  if (identifierNeedle) {
    const bySrc = webImages.find((img) => normalizeForMatch(img.src).includes(identifierNeedle));
    if (bySrc) return bySrc;
  }
  // Not every web src encodes the PDF's caption identifier - some are legacy
  // drawing codes (e.g. "graphics/eg/013/eg01395a") unrelated to the figure
  // number. The caption's own title text, though, mirrors the web image's
  // alt_text almost verbatim, so it's a reliable fallback key.
  const titleNeedle = normalizeForMatch(pdfImg.caption_title);
  if (!titleNeedle) return null;
  return webImages.find((img) => normalizeForMatch(img.alt_text) === titleNeedle) || null;
}

function renderComparePdfImage(img, index) {
  const container = document.getElementById("compare-pdf-content");
  container.innerHTML = "";
  const el = document.createElement("img");
  el.src = `/api/image/${index}`;
  container.appendChild(el);
  const label = document.createElement("div");
  label.textContent = imageLabel(img);
  container.appendChild(label);
}

function renderCompareWebImage(webImg) {
  const container = document.getElementById("compare-web-content");
  container.innerHTML = "";
  if (!webImg) {
    container.textContent = "No matching web image found.";
    return;
  }
  const el = document.createElement("img");
  el.src = webImageUrl(webImg);
  container.appendChild(el);
  const label = document.createElement("div");
  label.textContent = webImg.alt_text || "(no description)";
  container.appendChild(label);
}

function showCompareImages(img, index) {
  renderComparePdfImage(img, index);
  renderCompareWebImage(findMatchingWebImage(img, compareWebImages));
}

function renderCompareImageRow(img, index, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="/api/image/${index}"> ${imageLabel(img)}`;
  row.addEventListener("click", () => showCompareImages(img, index));
  return row;
}

function renderCompareImageTreeNode(node, depth) {
  const relevantChildren = node.children.filter(subtreeHasImages);
  const ownImages = node._images || [];
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `▸ ${formatNodeLabel(node)}`.trim();

  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    relevantChildren.forEach((child) => {
      childrenBox.appendChild(renderCompareImageTreeNode(child, depth + 1));
    });
    ownImages.forEach(({ img, index }) => {
      childrenBox.appendChild(renderCompareImageRow(img, index, depth + 1));
    });
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

async function loadCompareTab() {
  const content = document.getElementById("compare-tree-content");
  const declutter = document.getElementById("declutter-compare");

  const res = await fetch("/api/web-toc");
  compareWebImages = res.ok ? (await res.json()).images : [];

  function render() {
    content.innerHTML = "";
    attachImagesToOwners(declutter.checked);
    if (!subtreeHasImages(tocVolume)) return;
    content.appendChild(renderCompareImageTreeNode(tocVolume, 0));
  }
  declutter.addEventListener("change", render);
  render();
}

async function renderPage(pageNumber) {
  const page = await pdfDoc.getPage(pageNumber);
  const viewport = page.getViewport({ scale: 1.5 });
  const canvas = document.getElementById("page-canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
  document.getElementById("page-indicator").textContent = `Page ${pageNumber}`;
  currentPage = pageNumber;
  return viewport;
}

function showHighlight(viewport, bbox) {
  // bbox comes from PyMuPDF, which already uses a top-left-origin, y-down
  // coordinate system (like the canvas) - NOT the PDF spec's native
  // bottom-left-origin, y-up space that pdf.js's own
  // convertToViewportRectangle() expects for raw PDF-space coordinates.
  // Running our bbox through that conversion flips it vertically, so we
  // scale directly by the render scale instead.
  const scale = viewport.scale;
  const x0 = bbox.x0 * scale;
  const y0 = bbox.y0 * scale;
  const x1 = bbox.x1 * scale;
  const y1 = bbox.y1 * scale;
  const canvas = document.getElementById("page-canvas");
  const highlight = document.getElementById("highlight");
  highlight.style.display = "block";
  highlight.style.opacity = "1";
  highlight.style.left = `${canvas.offsetLeft + x0}px`;
  highlight.style.top = `${canvas.offsetTop + y0}px`;
  highlight.style.width = `${x1 - x0}px`;
  highlight.style.height = `${y1 - y0}px`;
  document.getElementById("main").scrollTo({ top: canvas.offsetTop + y0 - 80, behavior: "smooth" });
}

async function goToLocation(pageNumber, bbox) {
  const viewport = await renderPage(pageNumber);
  showHighlight(viewport, bbox);
}

const TABS = ["toc", "toc-web", "compare"];
const TAB_CONTENT_ID = { toc: "tree", "toc-web": "tree-web", compare: "compare" };
const TAB_ACTIVE_DISPLAY = { compare: "flex" };

function switchTab(active) {
  TABS.forEach((name) => {
    document.getElementById(`tab-${name}`).classList.toggle("active", name === active);
    document.getElementById(TAB_CONTENT_ID[name]).style.display =
      name === active ? TAB_ACTIVE_DISPLAY[name] || "block" : "none";
  });
  // The pdf canvas/controls and the web content panel share the same #main
  // pane - only one of them is meaningful for the active tab.
  const showPdf = active === "toc";
  document.getElementById("controls").style.display = showPdf ? "block" : "none";
  document.getElementById("page-canvas").style.display = showPdf ? "block" : "none";
  if (!showPdf) document.getElementById("highlight").style.display = "none";
  document.getElementById("web-content").style.display = active === "toc-web" ? "block" : "none";
}

TABS.forEach((name) => {
  document.getElementById(`tab-${name}`).addEventListener("click", () => switchTab(name));
});
document.getElementById("prev-page").addEventListener("click", () => {
  if (currentPage > 1) renderPage(currentPage - 1);
});
document.getElementById("next-page").addEventListener("click", () => {
  if (currentPage < pdfDoc.numPages) renderPage(currentPage + 1);
});
["filter-figures", "filter-equations", "filter-tables"].forEach((id) => {
  document.getElementById(id).addEventListener("change", renderTocTree);
});
["filter-web-figures", "filter-web-tables", "filter-web-body"].forEach((id) => {
  document.getElementById(id).addEventListener("change", renderTocWebTree);
});

(async function init() {
  pdfDoc = await pdfjsLib.getDocument("/pdf").promise;
  await renderPage(1);
  await loadToc();
  await loadAllImages();
  renderTocTree();
  await loadWebToc();
  await loadCompareTab();
})();
