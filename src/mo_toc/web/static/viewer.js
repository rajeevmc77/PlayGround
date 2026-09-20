import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let currentPage = 1;

async function loadToc() {
  const res = await fetch("/api/toc");
  const volume = await res.json();
  document.getElementById("tree").appendChild(renderNode(volume, 0));
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

async function loadImages() {
  const res = await fetch("/api/images");
  const images = await res.json();
  const container = document.getElementById("images");
  const declutter = document.getElementById("declutter");

  function render() {
    container.querySelectorAll(".image-row").forEach((el) => el.remove());
    const minDim = declutter.checked ? 40 : 0;
    images.forEach((img, index) => {
      const width = img.bbox.x1 - img.bbox.x0;
      const height = img.bbox.y1 - img.bbox.y0;
      if (Math.min(width, height) < minDim) return;
      const row = document.createElement("div");
      row.className = "image-row node-row";
      row.innerHTML = `<img src="/api/image/${index}/thumbnail"> p.${img.page} (${img.width}x${img.height})`;
      row.addEventListener("click", () => goToLocation(img.page, img.bbox));
      container.appendChild(row);
    });
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

document.getElementById("tab-toc").addEventListener("click", () => {
  document.getElementById("tab-toc").classList.add("active");
  document.getElementById("tab-images").classList.remove("active");
  document.getElementById("tree").style.display = "block";
  document.getElementById("images").style.display = "none";
});
document.getElementById("tab-images").addEventListener("click", () => {
  document.getElementById("tab-images").classList.add("active");
  document.getElementById("tab-toc").classList.remove("active");
  document.getElementById("images").style.display = "block";
  document.getElementById("tree").style.display = "none";
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
})();
