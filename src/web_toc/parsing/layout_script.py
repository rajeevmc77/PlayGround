"""The in-browser layout pass run over each locally saved page.

Everything is measured against the saved page's content panel,
`/html/body/main/div/main` (`main.ui-ContentPanel`) - the element the viewer
renders beside the PDF page:

- `xpath`: absolute, positional (`tag[n]` = n-th same-tag sibling), always
  starting at ROOT_XPATH, resolvable with `document.evaluate`.
- `bbox`: {x0, y0, x1, y1} in CSS px from the panel's top-left corner, in its
  fully scrolled-out content space - every scroll offset between the element
  and the panel is added back, so the numbers don't depend on scroll position.
- `text`: `innerText` with whitespace runs collapsed.

Measured only once the page's web fonts have loaded (`document.fonts.ready`):
the site's BC Sans is often still downloading when `load` fires, and text
measured in the narrower fallback font wraps onto fewer lines, shifting every
bbox below it.

Returns null when ROOT_XPATH doesn't resolve to exactly one content panel.
"""

ROOT_XPATH = "/html/body/main/div/main"

# `gridRows(block)`: the rendered rows of the table whose id sits on `block`,
# in order. A wide table is split into a header <table> and a body <table>
# (plus a `--pinned-col` duplicate of the header for its sticky first
# column); a table nested inside one of its cells is not one of its rows.
# Shared by the scraper's row counting and the layout pass.
GRID_ROWS_JS = """const gridRows = (block) => [...block.querySelectorAll('table')]
  .filter((table) => {
    if (table.classList.contains('table-block__table--pinned-col')) return false;
    const cell = table.parentElement.closest('td, th');
    return !cell || !block.contains(cell);
  })
  .flatMap((table) => [...table.rows]);"""

LAYOUT_JS = f"""async () => {{
  await document.fonts.ready;
  const ROOT = '{ROOT_XPATH}';
  const found = document.evaluate(ROOT, document, null,
    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  if (found.snapshotLength !== 1) return null;
  const root = found.snapshotItem(0);
  if (!root.matches('main.ui-ContentPanel')) return null;
  const origin = root.getBoundingClientRect();
  const round = (v) => Math.round(v * 100) / 100;

  const xpathOf = (el) => {{
    const steps = [];
    for (let node = el; node !== root; node = node.parentElement) {{
      let index = 1;
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {{
        if (sib.localName === node.localName) index++;
      }}
      steps.unshift(`${{node.localName}}[${{index}}]`);
    }}
    return [ROOT, ...steps].join('/');
  }};
  const bboxOf = (el) => {{
    let dx = 0, dy = 0;
    for (let a = el.parentElement; a && root.contains(a); a = a.parentElement) {{
      dx += a.scrollLeft; dy += a.scrollTop;
    }}
    const r = el.getBoundingClientRect();
    const x = r.left - origin.left + dx, y = r.top - origin.top + dy;
    return {{ x0: round(x), y0: round(y), x1: round(x + r.width), y1: round(y + r.height) }};
  }};
  // The text as displayed: like innerText, but with CSS generated content
  // (the site draws e.g. a compound reference's "[ ... ]" with ::before/
  // ::after), a space around every non-inline box, and display:none skipped.
  // Kept as [text, style] runs, style "b"/"i"/"bi"/"" from the computed
  // font-weight/font-style it renders in. Memoised - a table's text is built
  // from its already-walked cells.
  const cache = new Map();
  const styleOf = (cs) => (parseInt(cs.fontWeight, 10) >= 600 ? 'b' : '')
    + (cs.fontStyle === 'normal' ? '' : 'i');
  const generated = (el, which) => {{
    const cs = getComputedStyle(el, which);
    const match = cs.content.match(/^"(.*)"$/s);
    return match ? [[match[1].replace(/\\\\(.)/g, '$1'), styleOf(cs)]] : [];
  }};
  const rendered = (el) => {{
    if (cache.has(el)) return cache.get(el);
    const cs = getComputedStyle(el);
    let runs = [];
    if (cs.display !== 'none' && !(el instanceof SVGElement)) {{
      const own = styleOf(cs);
      const parts = [...el.childNodes].flatMap((child) =>
        child.nodeType === Node.TEXT_NODE ? [[child.nodeValue, own]]
          : child.nodeType === Node.ELEMENT_NODE ? rendered(child) : []);
      runs = [...generated(el, '::before'), ...parts, ...generated(el, '::after')];
      if (cs.display !== 'inline') runs = [[' ', ''], ...runs, [' ', '']];
    }}
    cache.set(el, runs);
    return runs;
  }};
  // Whitespace runs collapsed to one space and trimmed, across run
  // boundaries; emphasis as [start, end, style] ranges into that text.
  const styledOf = (el) => {{
    let text = '';
    const emphasis = [];
    for (const [raw, style] of rendered(el)) {{
      let piece = raw.replace(/\\s+/g, ' ');
      if (piece.startsWith(' ') && (text === '' || text.endsWith(' '))) piece = piece.slice(1);
      const last = emphasis[emphasis.length - 1];
      if (style && piece.trim()) {{
        if (last && last[1] === text.length && last[2] === style) last[1] += piece.length;
        else emphasis.push([text.length, text.length + piece.length, style]);
      }}
      text += piece;
    }}
    text = text.trimEnd();
    const clipped = emphasis.map(([s, e, style]) => [s, Math.min(e, text.length), style]);
    return {{ text, emphasis: clipped.filter(([s, e]) => s < e) }};
  }};
  const entry = (el) => ({{ xpath: xpathOf(el), ...styledOf(el), bbox: bboxOf(el) }});
  const inHtml = (el) => !el.closest('svg');

  const elements = {{}};
  for (const el of root.querySelectorAll('[id]')) {{
    if (inHtml(el)) elements[el.id] = entry(el);
  }}
  {GRID_ROWS_JS}
  const tables = {{}};
  for (const table of root.querySelectorAll('table')) {{
    const owner = table.closest('[id]');
    if (!owner || !root.contains(owner) || owner.id in tables) continue;
    tables[owner.id] = gridRows(owner).map((row) => ({{
      ...entry(row), cells: [...row.cells].map(entry),
    }}));
  }}
  const images = [...root.querySelectorAll('img:not(.equation-image)')].map((img) => ({{
    src: img.getAttribute('src') || '', xpath: xpathOf(img),
    text: img.getAttribute('alt') || '', bbox: bboxOf(img),
  }}));
  // The captured formula images (equation_script.py); a pinned-column copy
  // of a header cell is the same equation again, so it is left out.
  const equations = [...root.querySelectorAll('img.equation-image')]
    .filter((img) => !img.closest('.table-block__table--pinned-col'))
    .map((img) => ({{
      key: img.dataset.equation, owner: img.dataset.owner,
      text: img.getAttribute('alt') || '', xpath: xpathOf(img), bbox: bboxOf(img),
    }}));
  const headings = [...root.querySelectorAll('h1, h2, h3, h4, h5, h6')].map(entry);
  return {{ elements, tables, images, equations, headings }};
}}"""
