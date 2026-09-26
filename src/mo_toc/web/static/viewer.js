import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";
import {
  breadcrumbTrail,
  isNavNode,
  navIndent,
  pageOwner,
  scrollTargetId,
  siteNavLabel,
  sitePathKey,
  viewTarget,
} from "./web_toc_view.mjs?v=2";
import {
  classifyImage,
  collectUnifiedLocations,
  fitScale,
  minVisibleBox,
  pageFileRoute,
} from "./both_view.mjs?v=3";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";

let pdfDoc = null;
let currentPage = 1;
let tocVolume = null;
let allImages = null;
let webTocTree = null;
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

// The web TOC has no Figure/Equation split like the pdf's caption_kind - every
// web image is just "Figures" here. "Tables" are real structural content:
// either a "Table" node extracted from a section's own content (the web
// equivalent of the pdf's Table node, with the same Table -> Row -> Cell
// shape), or one of the site's own "spectables" special-tables index pages.
// "Body Text" is a "Sentence" node (the web equivalent of the pdf's Sentence
// node, with the same Sentence -> Clause -> Subclause shape). None of these
// is an image overlay, so all three count toward "keep this branch" on
// their own.
function subtreeHasWebTocContent(node, filters) {
  if (filters.figures && node._images && node._images.length > 0) return true;
  if (filters.tables && (node.type === "Table" || node.type === "spectables")) return true;
  if (filters.body && node.type === "Sentence") return true;
  return node.children.some((child) => subtreeHasWebTocContent(child, filters));
}

// The tab reproduces the live site itself: its own navigation-tree markup
// and CSS on the left (site-nav.css, extracted by build_web_pages.py), and
// its own scraped reading page on the right, in an iframe so the site's
// full stylesheet can't leak into the other tabs.
let webPages = new Set();
let webPathIndex = new Map();
let webNavControls = new Map();
let activeWebControl = null;
const OFFICIAL_SITE = "https://dev.buildingcode.gov.bc.ca";
const OFFICIAL_QUERY = "?version=2024&date=2024-03-08";

function webNavChildren(node, pruning, filters) {
  const children = node.children.filter(isNavNode);
  if (!pruning) return children;
  return children.filter((child) => subtreeHasWebTocContent(child, filters));
}

function createElement(tag, className) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  return el;
}

function renderNavTreeLink(node, depth, expandable) {
  const wrapper = createElement("div", "nav-tree-link-wrapper");
  wrapper.style.paddingLeft = `${navIndent(depth)}px`;
  // The site draws no selection bar beside a volume heading.
  if (node.type !== "volume") {
    wrapper.appendChild(createElement("div", "nav-tree-selection nav-tree-selection--inactive"));
  }
  const button = createElement("button", `nav-tree-link nav-tree-link--${node.type}`);
  if (expandable) button.setAttribute("aria-expanded", "false");
  const text = createElement("span", "nav-tree-text");
  const title = createElement("span", "nav-tree-title");
  title.textContent = siteNavLabel(node);
  text.appendChild(title);
  button.appendChild(text);
  wrapper.appendChild(button);
  return { wrapper, button };
}

function setActiveWebControl(control) {
  if (activeWebControl) activeWebControl.setActive(false);
  activeWebControl = control;
  if (control) control.setActive(true);
}

function renderTocWebNode(node, depth, pruning, filters, parentChain) {
  const chain = [...parentChain, node];
  const children = webNavChildren(node, pruning, filters);
  const item = createElement("div", "nav-tree-item");
  const { wrapper, button } = renderNavTreeLink(node, depth, children.length > 0);
  item.appendChild(wrapper);
  let childrenBox = null;

  const control = {
    expand(open = true) {
      if (!children.length) return;
      if (open && !childrenBox) {
        childrenBox = createElement("div", "nav-tree-children");
        childrenBox.setAttribute("role", "group");
        children.forEach((child) =>
          childrenBox.appendChild(renderTocWebNode(child, depth + 1, pruning, filters, chain))
        );
        item.appendChild(childrenBox);
      }
      if (childrenBox) childrenBox.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    },
    setActive(active) {
      wrapper.classList.toggle("nav-tree-link-wrapper--active", active);
      button.classList.toggle("nav-tree-link--active", active);
      const bar = wrapper.querySelector(".nav-tree-selection");
      if (bar) bar.className = `nav-tree-selection nav-tree-selection--${active ? "active" : "inactive"}`;
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    },
  };
  webNavControls.set(node.citation, control);

  button.addEventListener("click", () => {
    control.expand(button.getAttribute("aria-expanded") !== "true");
    // Volumes and divisions have no reading page on the site - its own
    // tree only expands them.
    if (node.type === "volume" || node.type === "division") return;
    setActiveWebControl(control);
    showWebReading(chain);
  });
  return item;
}

function webFilters() {
  return {
    figures: document.getElementById("filter-web-figures").checked,
    tables: document.getElementById("filter-web-tables").checked,
    body: document.getElementById("filter-web-body").checked,
  };
}

function renderTocWebTree() {
  const filters = webFilters();
  const pruning = filters.figures || filters.tables || filters.body;
  const content = document.getElementById("tree-web-content");
  content.innerHTML = "";
  webNavControls = new Map();
  activeWebControl = null;
  // The site opens with its first volume expanded; the root isn't shown.
  webNavChildren(webTocTree, pruning, filters).forEach((volume, index) => {
    content.appendChild(renderTocWebNode(volume, 0, pruning, filters, [webTocTree]));
    if (index === 0) webNavControls.get(volume.citation).expand();
  });
}

// Expands every ancestor so the node's own row exists, then selects it.
function revealWebNode(chain) {
  chain.slice(1, -1).forEach((ancestor) => webNavControls.get(ancestor.citation)?.expand());
  const control = webNavControls.get(chain[chain.length - 1].citation);
  setActiveWebControl(control || null);
  control?.expand();
}

function renderWebBreadcrumbs(chain) {
  const list = document.querySelector("#web-breadcrumbs .breadcrumbs-list");
  list.innerHTML = "";
  const trail = breadcrumbTrail(chain);
  trail.forEach((crumb, index) => {
    const li = createElement("li", "breadcrumbs-item");
    const link = createElement(crumb.navigable ? "a" : "span", "breadcrumbs-link");
    if (!crumb.navigable) link.classList.add("breadcrumbs-link--non-navigable");
    if (crumb.current) {
      link.classList.add("breadcrumbs-link--current");
      link.setAttribute("aria-current", "page");
    }
    if (crumb.navigable) {
      const crumbChain = chain.slice(0, chain.indexOf(crumb.node) + 1);
      link.href = "#";
      link.addEventListener("click", (event) => {
        event.preventDefault();
        navigateWeb(crumbChain);
      });
    }
    const title = createElement("span", "breadcrumbs-title");
    title.textContent = crumb.label;
    const tooltip = createElement("span", "breadcrumbs-tooltip");
    tooltip.setAttribute("role", "tooltip");
    tooltip.textContent = crumb.full;
    link.append(title, tooltip);
    li.appendChild(link);
    if (index < trail.length - 1) {
      const separator = createElement("span", "breadcrumbs-separator");
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = "/";
      li.appendChild(separator);
    }
    list.appendChild(li);
  });
}

// A subsection's or article's page on the site is its section page with
// just the Part title and that one block: <div class="sectionRenderer">
// holding only the block, no sectionTitle (confirmed against the live DOM).
function sliceToBlock(doc, target) {
  const isSubsection = target.type === "subsection";
  const heading = [...doc.querySelectorAll(isSubsection ? ".subsectionHeading" : ".articleHeading")]
    .find((el) => el.textContent.startsWith(`${target.identifier}. `));
  const block = heading?.closest(isSubsection ? ".subsectionBlock" : ".articleBlock");
  const renderer = doc.querySelector(".sectionRenderer");
  if (block && renderer) renderer.replaceChildren(block);
}

function interceptSiteLinks(doc) {
  doc.addEventListener("click", (event) => {
    const anchor = event.target.closest("a[href]");
    if (!anchor) return;
    event.preventDefault();
    const url = new URL(anchor.href);
    const chain = webPathIndex.get(sitePathKey(url.pathname));
    if (chain) navigateWeb(chain);
    else window.open(`${OFFICIAL_SITE}${url.pathname}${url.search}`, "_blank", "noopener");
  });
}

function applyWebView(doc, chain, owner) {
  const target = viewTarget(chain);
  if (target && chain.indexOf(target) > chain.indexOf(owner)) sliceToBlock(doc, target);
  interceptSiteLinks(doc);
  const scrollId = scrollTargetId(chain[chain.length - 1]);
  const element = scrollId ? doc.getElementById(scrollId) : null;
  if (element) element.scrollIntoView({ block: "start" });
  else doc.defaultView.scrollTo(0, 0);
}

function viewedChain(chain, owner) {
  const target = viewTarget(chain);
  const last = target && chain.indexOf(target) > chain.indexOf(owner) ? target : owner;
  return chain.slice(0, chain.indexOf(last) + 1);
}

function showWebReading(chain) {
  const owner = pageOwner(chain, webPages);
  const frame = document.getElementById("web-page-frame");
  const placeholder = document.getElementById("web-reading-placeholder");
  const link = document.getElementById("web-content-link");
  frame.hidden = !owner;
  placeholder.hidden = Boolean(owner);
  if (!owner) {
    renderWebBreadcrumbs(chain);
    placeholder.textContent = "No reading page for this item - run src/build_web_pages.py.";
    link.hidden = true;
    return;
  }
  const shown = viewedChain(chain, owner);
  renderWebBreadcrumbs(shown);
  const path = shown[shown.length - 1].path;
  link.href = `${OFFICIAL_SITE}${path}${OFFICIAL_QUERY}`;
  link.hidden = !path;
  frame.onload = () => applyWebView(frame.contentDocument, chain, owner);
  // Always a fresh load: a previous view may have sliced the same page's DOM.
  frame.src = `/web-page/${encodeURIComponent(owner.citation)}?t=${Date.now()}`;
}

function navigateWeb(chain) {
  revealWebNode(chain);
  showWebReading(chain);
}

function indexWebPaths(node, chain) {
  const nodeChain = [...chain, node];
  if (node.path && isNavNode(node)) webPathIndex.set(sitePathKey(node.path), nodeChain);
  node.children.forEach((child) => indexWebPaths(child, nodeChain));
}

async function loadWebPages() {
  const res = await fetch("/api/web-pages");
  webPages = res.ok ? new Set(Object.keys(await res.json())) : new Set();
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
  webImages = data.images;
  attachWebImagesToOwners(webTocTree, webImages);
  indexWebPaths(webTocTree, []);
  await loadWebPages();
  renderTocWebTree();
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

async function renderPage(pageNumber) {
  const viewport = await renderPdfPage("page-canvas", pageNumber, () => 1.5);
  document.getElementById("page-indicator").textContent = `Page ${pageNumber}`;
  currentPage = pageNumber;
  return viewport;
}

function showHighlight(viewport, bbox) {
  showPdfHighlight("page-canvas", "highlight", "main", viewport, bbox);
}

async function goToLocation(pageNumber, bbox) {
  const viewport = await renderPage(pageNumber);
  showHighlight(viewport, bbox);
}

// "Table of Contents - Both": one tree (the full pdf hierarchy, same as the
// pdf tab) drives two synchronized content panes. Filters only toggle which
// Figure/Equation/Image overlay rows attach to their owner - unlike the pdf
// tab, the structural tree itself is never pruned, since the whole point of
// this tab is to show every element down to Subclause.
function bothFilters() {
  return {
    figure: document.getElementById("filter-both-figures").checked,
    equation: document.getElementById("filter-both-equations").checked,
    image: document.getElementById("filter-both-images").checked,
  };
}

function clearAttachedBothImages(node) {
  delete node._bothImages;
  node.children.forEach(clearAttachedBothImages);
}

function attachBothImages(filters) {
  clearAttachedBothImages(tocVolume);
  const citationMap = buildCitationMap(tocVolume, {});
  allImages.forEach((img, index) => {
    if (!filters[classifyImage(img)]) return;
    const owner = citationMap[img.owner_citation];
    if (!owner) return;
    if (!owner._bothImages) owner._bothImages = [];
    owner._bothImages.push({ img, index });
  });
}

async function goToBothPdfLocation(pageNumber, bbox) {
  const colWidth = document.getElementById("both-pdf-col").clientWidth;
  const viewport = await renderPdfPage("both-pdf-canvas", pageNumber, (nativeWidth) =>
    fitScale(colWidth, nativeWidth)
  );
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

// The frame's own true, unscaled layout size (see the CSS comment on
// #both-web-frame) - never changed, so the saved page always reflows
// exactly as it did when build_web_pages.py captured its bbox coordinates.
const WEB_FRAME_WIDTH = 1500;
const WEB_FRAME_HEIGHT = 950;

// Visually shrinks/grows the iframe to the column's width with a CSS
// transform, which resizes nothing about its internal layout - .fit-wrap is
// sized to match so the column reserves exactly that much space instead of
// the frame's true footprint.
function fitWebFrameToColumn() {
  const scale = fitScale(document.getElementById("both-web-col").clientWidth, WEB_FRAME_WIDTH);
  document.getElementById("both-web-frame").style.transform = `scale(${scale})`;
  Object.assign(document.getElementById("both-web-fit").style, {
    width: `${WEB_FRAME_WIDTH * scale}px`,
    height: `${WEB_FRAME_HEIGHT * scale}px`,
  });
}

function showBothWebLocation(location) {
  const frame = document.getElementById("both-web-frame");
  const fitWrap = document.getElementById("both-web-fit");
  const placeholder = document.getElementById("both-web-placeholder");
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
  fitWebFrameToColumn();
  frame.onload = () => {
    expandReadingView(frame.contentDocument);
    highlightInFrame(frame.contentDocument, location.bbox);
  };
  frame.src = `${pageFileRoute(location.page_file)}?t=${Date.now()}`;
}

let bothSelection = null;

function selectBothNode(pageNumber, bbox, unifiedNumber) {
  bothSelection = { pageNumber, bbox, unifiedNumber };
  goToBothPdfLocation(pageNumber, bbox);
  showBothWebLocation(bothLocations.get(unifiedNumber) || null);
}

// A column's width can change after a selection is already showing (window
// resize, sidebar toggle) - re-fit both panes to it rather than leaving
// them sized for a column that no longer exists.
function refitBothPanels() {
  if (!bothSelection) return;
  const { pageNumber, bbox, unifiedNumber } = bothSelection;
  goToBothPdfLocation(pageNumber, bbox);
  if (bothLocations.get(unifiedNumber)) fitWebFrameToColumn();
}

function renderBothImageRow(img, index, depth) {
  const row = document.createElement("div");
  row.className = "image-row node-row";
  row.style.marginLeft = `${depth * 4}px`;
  row.innerHTML = `<img src="/api/image/${index}"> ${imageLabel(img)}`;
  row.addEventListener("click", () => selectBothNode(img.page, img.bbox, img.unified_number));
  return row;
}

function renderBothNode(node, depth) {
  const ownImages = node._bothImages || [];
  const hasChildren = node.children.length > 0 || ownImages.length > 0;
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
    node.children.forEach((child) => childrenBox.appendChild(renderBothNode(child, depth + 1)));
    ownImages.forEach(({ img, index }) => childrenBox.appendChild(renderBothImageRow(img, index, depth + 1)));
  });

  const wrapper = document.createElement("div");
  wrapper.appendChild(row);
  wrapper.appendChild(childrenBox);
  return wrapper;
}

function renderBothTree() {
  attachBothImages(bothFilters());
  const content = document.getElementById("both-tree-content");
  content.innerHTML = "";
  content.appendChild(renderBothNode(tocVolume, 0));
}

const TABS = ["toc", "toc-web", "toc-both", "compare"];
const TAB_CONTENT_ID = { toc: "tree", "toc-web": "tree-web", "toc-both": "toc-both", compare: "compare" };
const TAB_ACTIVE_DISPLAY = { "toc-both": "flex", compare: "flex" };

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
  document.getElementById("web-reading").style.display = active === "toc-web" ? "flex" : "none";
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
["filter-both-figures", "filter-both-equations", "filter-both-images"].forEach((id) => {
  document.getElementById(id).addEventListener("change", renderBothTree);
});

let resizeDebounce = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeDebounce);
  resizeDebounce = setTimeout(refitBothPanels, 150);
});

(async function init() {
  pdfDoc = await pdfjsLib.getDocument("/pdf").promise;
  await renderPage(1);
  await loadToc();
  await loadAllImages();
  renderTocTree();
  await loadWebToc();
  if (webTocTree) bothLocations = collectUnifiedLocations(webTocTree, webImages);
  renderBothTree();
  await loadCompareTab();
})();
