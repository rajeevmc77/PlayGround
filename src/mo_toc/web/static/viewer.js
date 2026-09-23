import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let currentPage = 1;
let tocVolume = null;
let allImages = null;

function formatNodeLabel(node) {
  const text = node.title || node.content;
  return [node.unified_number, node.type, node.identifier, text].filter(Boolean).join(" ");
}

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
  row.textContent = `${hasChildren ? "▸ " : ""}${formatNodeLabel(node)}`.trim();
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

async function loadImages() {
  const res = await fetch("/api/images");
  allImages = await res.json();
  const container = document.getElementById("images");
  const declutter = document.getElementById("declutter");

  function render() {
    container.querySelectorAll(".image-row").forEach((el) => el.remove());
    allImages.forEach((img, index) => {
      if (isHiddenByDeclutter(img, declutter.checked)) return;
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

function renderImageTreeNode(node, depth) {
  const relevantChildren = node.children.filter(subtreeHasImages);
  const ownImages = node._images || [];
  const row = document.createElement("div");
  row.className = "node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.textContent = `▸ ${formatNodeLabel(node)}`.trim();

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
    attachImagesToOwners(declutter.checked);
    if (!subtreeHasImages(tocVolume)) return;
    content.appendChild(renderImageTreeNode(tocVolume, 0));
  }
  declutter.addEventListener("change", render);
  render();
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

function subtreeHasWebImages(node) {
  if (node._images && node._images.length > 0) return true;
  return node.children.some(subtreeHasWebImages);
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

function renderWebTreeNode(node, depth) {
  const relevantChildren = node.children.filter(subtreeHasWebImages);
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
    relevantChildren.forEach((child) => childrenBox.appendChild(renderWebTreeNode(child, depth + 1)));
    ownImages.forEach((img) => childrenBox.appendChild(renderWebImageRow(img, node, depth + 1)));
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

async function loadWebToc() {
  const content = document.getElementById("web-image-tree-content");
  const res = await fetch("/api/web-toc");
  if (!res.ok) {
    content.textContent = "Not built yet - run src/build_web_toc.py, then reload.";
    return;
  }
  const data = await res.json();
  attachWebImagesToOwners(data.tree, data.images);
  content.innerHTML = "";
  if (subtreeHasWebImages(data.tree)) {
    content.appendChild(renderWebTreeNode(data.tree, 0));
  }
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

const TABS = ["toc", "images", "image-tree", "web-images", "compare"];
const TAB_CONTENT_ID = {
  toc: "tree", images: "images", "image-tree": "image-tree", "web-images": "web-images",
  compare: "compare",
};
const TAB_ACTIVE_DISPLAY = { compare: "flex" };

function switchTab(active) {
  TABS.forEach((name) => {
    document.getElementById(`tab-${name}`).classList.toggle("active", name === active);
    document.getElementById(TAB_CONTENT_ID[name]).style.display =
      name === active ? TAB_ACTIVE_DISPLAY[name] || "block" : "none";
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
  await loadWebToc();
  await loadCompareTab();
})();
