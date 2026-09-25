// Pure helpers for the "Table of Contents - web" tab: they decide how the
// live BC Building Code site itself names, indents and slices things, so
// the viewer can reproduce its navigation tree and reading pages exactly.
// No DOM access here - see tests/js/web_toc_view.test.mjs.

// Body content extracted below article level. The site's own navigation
// tree stops at articles; these live only inside the reading page.
const BODY_TYPES = new Set(["Sentence", "Clause", "Subclause", "Table", "Row", "Cell", "Note"]);

// The site's navigation data titles numbered levels "1.1 General", but its
// tree, headings and breadcrumbs all render them "1.1. General".
const NUMBERED_TYPES = new Set(["section", "subsection", "article"]);

// A subsection's or article's page on the site is its section page cut
// down to that one block (build_web_pages.py only scrapes the section).
const SLICED_TYPES = new Set(["subsection", "article"]);

// The site shows these in the breadcrumb but never links them - it has no
// reading page for either.
const UNLINKED_CRUMB_TYPES = new Set(["volume", "division"]);

const CRUMB_MAX_CHARS = 24;
const CRUMB_LEVELS_SHOWN = 2;

export function siteNavLabel(node) {
  const prefix = `${node.identifier} `;
  if (!NUMBERED_TYPES.has(node.type) || !node.identifier || !node.title.startsWith(prefix)) {
    return node.title;
  }
  return `${node.identifier}. ${node.title.slice(prefix.length)}`;
}

export function isNavNode(node) {
  return !BODY_TYPES.has(node.type);
}

// Matches the site's inline padding-left per depth: volume 0, then 32px
// for its children and +16px per level below.
export function navIndent(depth) {
  return depth === 0 ? 0 : 16 + depth * 16;
}

// `chain` is always root-first: [root, volume, ..., clickedNode].
export function pageOwner(chain, pages) {
  for (let i = chain.length - 1; i >= 0; i -= 1) {
    if (pages.has(chain[i].citation)) return chain[i];
  }
  return null;
}

export function viewTarget(chain) {
  for (let i = chain.length - 1; i >= 0; i -= 1) {
    if (SLICED_TYPES.has(chain[i].type)) return chain[i];
  }
  return null;
}

// The site renders every sentence/clause/table block with its citation as
// the element id.
export function scrollTargetId(node) {
  return BODY_TYPES.has(node.type) ? node.citation : null;
}

// Navigation data paths have no trailing slash; the site's own in-page
// links (e.g. a Part page's section cards) do.
export function sitePathKey(pathname) {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

export function truncateCrumb(text) {
  return text.length > CRUMB_MAX_CHARS ? `${text.slice(0, CRUMB_MAX_CHARS)}...` : text;
}

function crumb(node, current) {
  const full = siteNavLabel(node);
  const navigable = !current && !UNLINKED_CRUMB_TYPES.has(node.type);
  return { label: truncateCrumb(full), full, node, current, navigable };
}

// Home, then (volume and root skipped) the last two levels of the chain -
// with "..." standing in for anything above them - exactly as the site does.
export function breadcrumbTrail(chain) {
  const home = { label: "Home", full: "Home", node: null, current: false, navigable: false };
  const levels = chain.filter((n) => n.type !== "root" && n.type !== "volume");
  const shown = levels.slice(-CRUMB_LEVELS_SHOWN);
  const crumbs = shown.map((n, i) => crumb(n, i === shown.length - 1));
  if (levels.length <= CRUMB_LEVELS_SHOWN) return [home, ...crumbs];
  const ellipsis = { label: "...", full: "...", node: null, current: false, navigable: false };
  return [home, ellipsis, ...crumbs];
}
