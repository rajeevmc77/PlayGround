import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";
import {
  bothHostCitations,
  classifyImage,
  collectUnifiedLocations,
  fitScale,
  minVisibleBox,
  pageFileRoute,
  visibleBothChildren,
} from "./both_view.mjs?v=3";
import { filterIds, statusBadge } from "./compare_view.mjs?v=1";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let tocVolume = null;
let allImages = null;
let webImages = [];
let unifiedLocations = new Map();
let comparisonStatuses = new Map();

function formatNodeLabel(node) {
  const text = node.title || node.content;
  return [node.unified_number, node.type, node.identifier, text].filter(Boolean).join(" ");
}

function imageLabel(img) {
  if (img.caption_identifier) return `${img.caption_kind} ${img.caption_identifier}`;
  return `p.${img.page} (${img.width}x${img.height})`;
}

async function loadToc() {
  const res = await fetch("/api/toc");
  tocVolume = await res.json();
}

async function loadAllImages() {
  const res = await fetch("/api/images");
  allImages = await res.json();
}

// The web index only feeds the Both/Compare tabs' unified_number lookup;
// without it both still show the pdf side, with no matching web content.
async function loadWebToc() {
  const res = await fetch("/api/web-toc");
  if (!res.ok) return;
  const data = await res.json();
  webImages = data.images;
  unifiedLocations = collectUnifiedLocations(data.tree, webImages);
}

// Precomputed offline by build_comparison.py; without it the Compare tab
// still renders, just with no tick/cross badges.
async function loadComparison() {
  const res = await fetch("/api/comparison");
  if (!res.ok) return;
  const data = await res.json();
  comparisonStatuses = new Map(Object.entries(data.statuses || {}));
}

function buildCitationMap(node, map) {
  map[node.citation] = node;
  node.children.forEach((child) => buildCitationMap(child, map));
  return map;
}

function clearAttached(node, key) {
  delete node[key];
  node.children.forEach((child) => clearAttached(child, key));
}

// Figures/Equations/Images gate which image rows attach; Tables/Text show
// or hide tree rows themselves (see both_view.mjs). Both tabs share this
// same filtering logic - `key` just keeps their attached-image state apart
// so switching tabs never shows the other tab's filter selection.
function attachFilteredImages(filters, key) {
  clearAttached(tocVolume, key);
  const citationMap = buildCitationMap(tocVolume, {});
  const hosts = bothHostCitations(tocVolume, filters);
  allImages.forEach((img, index) => {
    if (!filters[classifyImage(img)]) return;
    const host = citationMap[hosts.get(img.owner_citation)];
    if (!host) return;
    if (!host[key]) host[key] = [];
    host[key].push({ img, index });
  });
}

// `scaleFn` picks the render scale from the page's native (scale:1) width -
// pdf.js can rasterize at any scale directly, so "fit the column width"
// needs no separate CSS resizing step; showPdfHighlight already keys its
// bbox math off the actual viewport.scale used here, so it stays correct
// whatever scale is chosen.
async function renderPdfPage(canvasId, pageNumber, scaleFn) {
  const page = await pdfDoc.getPage(pageNumber);
  const nativeWidth = page.getViewport({ scale: 1 }).width;
  const viewport = page.getViewport({ scale: scaleFn(nativeWidth) });
  const canvas = document.getElementById(canvasId);
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
  return viewport;
}

// bbox comes from PyMuPDF, which already uses a top-left-origin, y-down
// coordinate system (like the canvas) - NOT the PDF spec's native
// bottom-left-origin, y-up space that pdf.js's own
// convertToViewportRectangle() expects for raw PDF-space coordinates.
// Running our bbox through that conversion flips it vertically, so we
// scale directly by the render scale instead.
function showPdfHighlight(canvasId, highlightId, scrollContainerId, viewport, bbox) {
  const scale = viewport.scale;
  const x0 = bbox.x0 * scale;
  const y0 = bbox.y0 * scale;
  const x1 = bbox.x1 * scale;
  const y1 = bbox.y1 * scale;
  const canvas = document.getElementById(canvasId);
  const highlight = document.getElementById(highlightId);
  highlight.style.display = "block";
  highlight.style.opacity = "1";
  highlight.style.left = `${canvas.offsetLeft + x0}px`;
  highlight.style.top = `${canvas.offsetTop + y0}px`;
  highlight.style.width = `${x1 - x0}px`;
  highlight.style.height = `${y1 - y0}px`;
  document.getElementById(scrollContainerId).scrollTo({ top: canvas.offsetTop + y0 - 80, behavior: "smooth" });
}

// The content panel every saved page's bbox is measured from (see
// layout_join.py / the web-toc-local-scrape design doc).
const WEB_PANEL_XPATH = "/html/body/main/div/main";

// Appends the highlight as the panel's own child and positions it with the
// bbox directly, rather than computing a page-relative position via
// getBoundingClientRect()+scroll - immune to whatever positioning context
// the site's own CSS puts around the panel, and to any scroll/layout timing
// at the moment of measurement.
function highlightInFrame(doc, bbox) {
  const panel = doc.evaluate(WEB_PANEL_XPATH, doc, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null)
    .singleNodeValue;
  if (!panel) return;
  if (doc.defaultView.getComputedStyle(panel).position === "static") panel.style.position = "relative";
  const box = minVisibleBox(bbox);
  let highlight = doc.getElementById("both-web-injected-highlight");
  if (!highlight) {
    highlight = doc.createElement("div");
    highlight.id = "both-web-injected-highlight";
    highlight.style.cssText =
      "position:absolute; border:2px solid red; background:rgba(255,0,0,0.15); pointer-events:none; z-index:9999;";
    panel.appendChild(highlight);
  }
  Object.assign(highlight.style, {
    left: `${box.left}px`,
    top: `${box.top}px`,
    width: `${box.width}px`,
    height: `${box.height}px`,
  });
  highlight.scrollIntoView({ block: "center" });
}

// The live site's own "reading-view" widget sizes itself at runtime (the
// SPA measures the viewport in JS); our static page snapshot can't
// reproduce that, so on some pages it's left collapsed to a few px with
// overflow hidden, clipping all its content. Force it to its natural
// height so the saved page's full content is actually visible/scrollable
// once loaded standalone in our iframe.
function expandReadingView(doc) {
  const style = doc.createElement("style");
  style.textContent = ".reading-view, .reading-view__content { height: auto !important; overflow: visible !important; }";
  doc.head.appendChild(style);
}

// The frame's own true, unscaled layout size (see the CSS comment on
// #both-web-frame) - never changed, so the saved page always reflows
// exactly as it did when build_web_pages.py captured its bbox coordinates.
const WEB_FRAME_WIDTH = 1500;
const WEB_FRAME_HEIGHT = 950;

// Visually shrinks/grows the iframe to the column's width with a CSS
// transform, which resizes nothing about its internal layout - the fit
// wrapper is sized to match so the column reserves exactly that much space
// instead of the frame's true footprint.
function fitWebFrameToColumn(ids) {
  const scale = fitScale(document.getElementById(ids.webColId).clientWidth, WEB_FRAME_WIDTH);
  document.getElementById(ids.webFrameId).style.transform = `scale(${scale})`;
  Object.assign(document.getElementById(ids.webFitId).style, {
    width: `${WEB_FRAME_WIDTH * scale}px`,
    height: `${WEB_FRAME_HEIGHT * scale}px`,
  });
}

function showWebLocation(ids, location) {
  const frame = document.getElementById(ids.webFrameId);
  const fitWrap = document.getElementById(ids.webFitId);
  const placeholder = document.getElementById(ids.webPlaceholderId);
  if (!location) {
    frame.hidden = true;
    fitWrap.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = "No matching web content for this item.";
    return;
  }
  frame.hidden = false;
  fitWrap.hidden = false;
  placeholder.hidden = true;
  fitWebFrameToColumn(ids);
  frame.onload = () => {
    expandReadingView(frame.contentDocument);
    highlightInFrame(frame.contentDocument, location.bbox);
  };
  frame.src = `${pageFileRoute(location.page_file)}?t=${Date.now()}`;
}

async function goToPdfLocation(ids, pageNumber, bbox) {
  const colWidth = document.getElementById(ids.pdfColId).clientWidth;
  const viewport = await renderPdfPage(ids.pdfCanvasId, pageNumber, (nativeWidth) =>
    fitScale(colWidth, nativeWidth)
  );
  // The pane only sizes to its content; the column is the actual
  // overflow:auto ancestor that scrolling needs to target.
  showPdfHighlight(ids.pdfCanvasId, ids.pdfHighlightId, ids.pdfColId, viewport, bbox);
}

// One tree (the full pdf hierarchy) drives two synchronized content panes -
// the pattern both the "Both" and "Compare" tabs use, parameterized on
// their own element ids so neither tab duplicates the other's panel logic.
function createSplitPanel(ids) {
  let selection = null;

  function select(pageNumber, bbox, unifiedNumber) {
    selection = { pageNumber, bbox, unifiedNumber };
    goToPdfLocation(ids, pageNumber, bbox);
    showWebLocation(ids, unifiedLocations.get(unifiedNumber) || null);
  }

  // A column's width can change after a selection is already showing
  // (window resize, sidebar toggle) - re-fit both panes to it rather than
  // leaving them sized for a column that no longer exists.
  function refit() {
    if (!selection) return;
    const { pageNumber, bbox, unifiedNumber } = selection;
    goToPdfLocation(ids, pageNumber, bbox);
    if (unifiedLocations.get(unifiedNumber)) fitWebFrameToColumn(ids);
  }

  return { select, refit };
}

const bothPanel = createSplitPanel({
  pdfColId: "both-pdf-col",
  pdfCanvasId: "both-pdf-canvas",
  pdfHighlightId: "both-pdf-highlight",
  webColId: "both-web-col",
  webFrameId: "both-web-frame",
  webFitId: "both-web-fit",
  webPlaceholderId: "both-web-placeholder",
});

const comparePanel = createSplitPanel({
  pdfColId: "compare-pdf-col",
  pdfCanvasId: "compare-pdf-canvas",
  pdfHighlightId: "compare-pdf-highlight",
  webColId: "compare-web-col",
  webFrameId: "compare-web-frame",
  webFitId: "compare-web-fit",
  webPlaceholderId: "compare-web-placeholder",
});

function appendStatusBadge(row, unifiedNumber) {
  const badge = statusBadge(comparisonStatuses.get(unifiedNumber));
  const icon = document.createElement("span");
  icon.className = `status-icon ${badge.className}`;
  icon.textContent = badge.glyph;
  row.appendChild(icon);
}

function renderTocImageRow(img, index, depth, panel, showStatus) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  if (showStatus) appendStatusBadge(row, img.unified_number);
  row.appendChild(document.createTextNode(" "));
  const thumb = document.createElement("img");
  thumb.src = `/api/image/${index}`;
  row.appendChild(thumb);
  row.appendChild(document.createTextNode(` ${imageLabel(img)}`));
  row.addEventListener("click", () => panel.select(img.page, img.bbox, img.unified_number));
  return row;
}

function renderTocNode(node, depth, filters, imagesKey, panel, showStatus) {
  const children = visibleBothChildren(node, filters);
  const ownImages = node[imagesKey] || [];
  const hasChildren = children.length > 0 || ownImages.length > 0;
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  if (showStatus) appendStatusBadge(row, node.unified_number);
  row.appendChild(
    document.createTextNode(` ${hasChildren ? "▸ " : ""}${formatNodeLabel(node)}`.trim())
  );
  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    panel.select(node.page, node.bbox, node.unified_number);
    if (!hasChildren) return;
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    children.forEach((child) =>
      childrenBox.appendChild(renderTocNode(child, depth + 1, filters, imagesKey, panel, showStatus))
    );
    ownImages.forEach(({ img, index }) =>
      childrenBox.appendChild(renderTocImageRow(img, index, depth + 1, panel, showStatus))
    );
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

const BOTH_FILTER_IDS = filterIds("both");
const COMPARE_FILTER_IDS = filterIds("compare");

function readFilters(idsByKey) {
  return Object.fromEntries(
    Object.entries(idsByKey).map(([key, id]) => [key, document.getElementById(id).checked])
  );
}

function renderBothTree() {
  const filters = readFilters(BOTH_FILTER_IDS);
  attachFilteredImages(filters, "_bothImages");
  const content = document.getElementById("both-tree-content");
  content.innerHTML = "";
  content.appendChild(renderTocNode(tocVolume, 0, filters, "_bothImages", bothPanel, false));
}

function renderCompareTree() {
  const filters = readFilters(COMPARE_FILTER_IDS);
  attachFilteredImages(filters, "_compareImages");
  const content = document.getElementById("compare-tree-content");
  content.innerHTML = "";
  content.appendChild(renderTocNode(tocVolume, 0, filters, "_compareImages", comparePanel, true));
}

const TABS = ["toc-both", "compare"];

function switchTab(active) {
  TABS.forEach((name) => {
    document.getElementById(`tab-${name}`).classList.toggle("active", name === active);
    document.getElementById(name).style.display = name === active ? "flex" : "none";
  });
}

TABS.forEach((name) => {
  document.getElementById(`tab-${name}`).addEventListener("click", () => switchTab(name));
});
Object.values(BOTH_FILTER_IDS).forEach((id) => {
  document.getElementById(id).addEventListener("change", renderBothTree);
});
Object.values(COMPARE_FILTER_IDS).forEach((id) => {
  document.getElementById(id).addEventListener("change", renderCompareTree);
});

let resizeDebounce = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeDebounce);
  resizeDebounce = setTimeout(() => {
    bothPanel.refit();
    comparePanel.refit();
  }, 150);
});

(async function init() {
  pdfDoc = await pdfjsLib.getDocument("/pdf").promise;
  await loadToc();
  await loadAllImages();
  await loadWebToc();
  await loadComparison();
  renderBothTree();
  renderCompareTree();
})();
