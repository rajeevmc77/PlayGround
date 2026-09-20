import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let currentPage = 1;
let tocVolume = null;
let allImages = null;

async function loadToc() {
  const res = await fetch("/api/toc");
  tocVolume = await res.json();
  document.getElementById("tree").appendChild(renderNode(tocVolume, 0));
}

function renderNode(node, depth) {
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  const hasChildren = node.children && node.children.length > 0;
  row.textContent = `${hasChildren ? "▸ " : ""}${node.type} ${node.identifier} ${node.title}`.trim();
  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    goToLocation(node.page, node.bbox);
    if (!hasChildren) return;
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length === 0) {
      node.children.forEach((child) => childrenBox.appendChild(renderNode(child, depth + 1)));
    }
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

function imageIsBelowMinDim(img, minDim) {
  const width = img.bbox.x1 - img.bbox.x0;
  const height = img.bbox.y1 - img.bbox.y0;
  return Math.min(width, height) < minDim;
}

function imageLabel(img) {
  if (img.caption_identifier) return `${img.caption_kind} ${img.caption_identifier}`;
  return `p.${img.page} (${img.width}x${img.height})`;
}

function renderImageRow(img, index, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="/api/image/${index}/thumbnail"> ${imageLabel(img)}`;
  row.addEventListener("click", () => goToLocation(img.page, img.bbox));
  return row;
}

async function loadImages() {
  const res = await fetch("/api/images");
  allImages = await res.json();
  const container = document.getElementById("images");
  const declutter = document.getElementById("declutter");

  function render() {
    container.querySelectorAll(".image-row").forEach((el) => el.remove());
    const minDim = declutter.checked ? 40 : 0;
    allImages.forEach((img, index) => {
      if (imageIsBelowMinDim(img, minDim)) return;
      container.appendChild(renderImageRow(img, index, 0));
    });
  }
  declutter.addEventListener("change", render);
  render();
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

function attachImagesToOwners(minDim) {
  clearAttachedImages(tocVolume);
  const citationMap = buildCitationMap(tocVolume, {});
  allImages.forEach((img, index) => {
    if (imageIsBelowMinDim(img, minDim)) return;
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

function renderImageTreeNode(node, depth) {
  const relevantChildren = node.children.filter(subtreeHasImages);
  const ownImages = node._images || [];
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `▸ ${node.type} ${node.identifier} ${node.title}`.trim();

  const childrenBox = document.createElement("div");
  childrenBox.className = "node-children";

  row.addEventListener("click", () => {
    goToLocation(node.page, node.bbox);
    childrenBox.classList.toggle("expanded");
    if (childrenBox.children.length > 0) return;
    relevantChildren.forEach((child) => {
      childrenBox.appendChild(renderImageTreeNode(child, depth + 1));
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

async function loadImageTree() {
  const content = document.getElementById("image-tree-content");
  const declutter = document.getElementById("declutter-tree");

  function render() {
    content.innerHTML = "";
    attachImagesToOwners(declutter.checked ? 40 : 0);
    if (!subtreeHasImages(tocVolume)) return;
    content.appendChild(renderImageTreeNode(tocVolume, 0));
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

const TABS = ["toc", "images", "image-tree"];
const TAB_CONTENT_ID = { toc: "tree", images: "images", "image-tree": "image-tree" };

function switchTab(active) {
  TABS.forEach((name) => {
    document.getElementById(`tab-${name}`).classList.toggle("active", name === active);
    document.getElementById(TAB_CONTENT_ID[name]).style.display =
      name === active ? "block" : "none";
  });
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

(async function init() {
  pdfDoc = await pdfjsLib.getDocument("/pdf").promise;
  await renderPage(1);
  await loadToc();
  await loadImages();
  await loadImageTree();
})();
