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

Returns null when ROOT_XPATH doesn't resolve to exactly one content panel.
"""

ROOT_XPATH = "/html/body/main/div/main"

LAYOUT_JS = f"""() => {{
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
  // Memoised - a table's text is built from its already-walked cells.
  const cache = new Map();
  const generated = (el, which) => {{
    const match = getComputedStyle(el, which).content.match(/^"(.*)"$/s);
    return match ? match[1].replace(/\\\\(.)/g, '$1') : '';
  }};
  const rendered = (el) => {{
    if (cache.has(el)) return cache.get(el);
    const display = getComputedStyle(el).display;
    let text = '';
    if (display !== 'none' && !(el instanceof SVGElement)) {{
      const parts = [...el.childNodes].map((child) =>
        child.nodeType === Node.TEXT_NODE ? child.nodeValue
          : child.nodeType === Node.ELEMENT_NODE ? rendered(child) : '');
      text = generated(el, '::before') + parts.join('') + generated(el, '::after');
      if (display !== 'inline') text = ` ${{text}} `;
    }}
    cache.set(el, text);
    return text;
  }};
  const textOf = (el) => rendered(el).replace(/\\s+/g, ' ').trim();
  const entry = (el) => ({{ xpath: xpathOf(el), text: textOf(el), bbox: bboxOf(el) }});
  const inHtml = (el) => !el.closest('svg');

  const elements = {{}};
  for (const el of root.querySelectorAll('[id]')) {{
    if (inHtml(el)) elements[el.id] = entry(el);
  }}
  const tables = {{}};
  for (const table of root.querySelectorAll('table')) {{
    const owner = table.closest('[id]');
    if (!owner || !root.contains(owner) || owner.id in tables) continue;
    tables[owner.id] = [...table.rows].map((row) => ({{
      ...entry(row), cells: [...row.cells].map(entry),
    }}));
  }}
  const images = [...root.querySelectorAll('img')].map((img) => ({{
    src: img.getAttribute('src') || '', xpath: xpathOf(img),
    text: img.getAttribute('alt') || '', bbox: bboxOf(img),
  }}));
  const headings = [...root.querySelectorAll('h1, h2, h3, h4, h5, h6')].map(entry);
  return {{ elements, tables, images, headings }};
}}"""
