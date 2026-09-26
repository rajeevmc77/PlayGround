import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";
import {
  bothHostCitations,
  classifyImage,
  collectUnifiedLocations,
  minVisibleBox,
  pageFileRoute,
  visibleBothChildren,
} from "./both_view.mjs?v=3";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let tocVolume = null;
let allImages = null;
let webImages = [];
let bothLocations = new Map();

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

// The web index only feeds the Both tab's unified_number lookup and the
// Compare tab's web-image column; without it both still show the pdf side.
async function loadWebToc() {
  const res = await fetch("/api/web-toc");
  if (!res.ok) return;
  const data = await res.json();
  webImages = data.images;
  bothLocations = collectUnifiedLocations(data.tree, webImages);
}

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
  renderCompareWebImage(findMatchingWebImage(img, webImages));
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

  function render() {
    content.innerHTML = "";
    attachImagesToOwners(declutter.checked);
    if (!subtreeHasImages(tocVolume)) return;
    content.appendChild(renderCompareImageTreeNode(tocVolume, 0));
  }
  declutter.addEventListener("change", render);
  render();
}

async function renderPdfPage(canvasId, pageNumber) {
  const page = await pdfDoc.getPage(pageNumber);
  const viewport = page.getViewport({ scale: 1.5 });
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

// "Table of Contents - Both": one tree (the full pdf hierarchy) drives two
// synchronized content panes. Figures/Equations/Images toggle which image
// rows attach; Tables/Text show or hide those rows of the tree itself
// (headings always stay - see both_view.mjs). An image whose owner row is
// hidden attaches to the nearest row still shown.
const BOTH_FILTERS = {
  figure: "filter-both-figures",
  table: "filter-both-tables",
  equation: "filter-both-equations",
  text: "filter-both-text",
  image: "filter-both-images",
};
const BOTH_FILTER_IDS = Object.values(BOTH_FILTERS);

function bothFilters() {
  return Object.fromEntries(
    Object.entries(BOTH_FILTERS).map(([key, id]) => [key, document.getElementById(id).checked])
  );
}

function clearAttachedBothImages(node) {
  delete node._bothImages;
  node.children.forEach(clearAttachedBothImages);
}

function attachBothImages(filters) {
  clearAttachedBothImages(tocVolume);
  const citationMap = buildCitationMap(tocVolume, {});
  const hosts = bothHostCitations(tocVolume, filters);
  allImages.forEach((img, index) => {
    if (!filters[classifyImage(img)]) return;
    const host = citationMap[hosts.get(img.owner_citation)];
    if (!host) return;
    if (!host._bothImages) host._bothImages = [];
    host._bothImages.push({ img, index });
  });
}

async function goToBothPdfLocation(pageNumber, bbox) {
  const viewport = await renderPdfPage("both-pdf-canvas", pageNumber);
  // "both-pdf-pane" only sizes to its content; "both-pdf-col" is the actual
  // overflow:auto ancestor that scrolling needs to target.
  showPdfHighlight("both-pdf-canvas", "both-pdf-highlight", "both-pdf-col", viewport, bbox);
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

function showBothWebLocation(location) {
  const frame = document.getElementById("both-web-frame");
  const placeholder = document.getElementById("both-web-placeholder");
  if (!location) {
    frame.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = "No matching web content for this item.";
    return;
  }
  frame.hidden = false;
  placeholder.hidden = true;
  frame.onload = () => {
    expandReadingView(frame.contentDocument);
    highlightInFrame(frame.contentDocument, location.bbox);
  };
  frame.src = `${pageFileRoute(location.page_file)}?t=${Date.now()}`;
}

function selectBothNode(pageNumber, bbox, unifiedNumber) {
  goToBothPdfLocation(pageNumber, bbox);
  showBothWebLocation(bothLocations.get(unifiedNumber) || null);
}

function renderBothImageRow(img, index, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="/api/image/${index}"> ${imageLabel(img)}`;
  row.addEventListener("click", () => selectBothNode(img.page, img.bbox, img.unified_number));
  return row;
}

function renderBothNode(node, depth, filters) {
  const children = visibleBothChildren(node, filters);
  const ownImages = node._bothImages || [];
  const hasChildren = children.length > 0 || ownImages.length > 0;
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `${hasChildren ? "▸ " : ""}${formatNodeLabel(node)}`.trim();
  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    selectBothNode(node.page, node.bbox, node.unified_number);
    if (!hasChildren) return;
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    children.forEach((child) => childrenBox.appendChild(renderBothNode(child, depth + 1, filters)));
    ownImages.forEach(({ img, index }) => childrenBox.appendChild(renderBothImageRow(img, index, depth + 1)));
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

function renderBothTree() {
  const filters = bothFilters();
  attachBothImages(filters);
  const content = document.getElementById("both-tree-content");
  content.innerHTML = "";
  content.appendChild(renderBothNode(tocVolume, 0, filters));
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
BOTH_FILTER_IDS.forEach((id) => {
  document.getElementById(id).addEventListener("change", renderBothTree);
});

(async function init() {
  pdfDoc = await pdfjsLib.getDocument("/pdf").promise;
  await loadToc();
  await loadAllImages();
  await loadWebToc();
  renderBothTree();
  await loadCompareTab();
})();
