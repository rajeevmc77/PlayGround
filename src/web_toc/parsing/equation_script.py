"""The in-browser equation capture run over each locally saved page.

The site renders every formula - the content JSON's `display`/`inline`
LaTeX/MathML nodes - with MathJax into a `.equation-block`: a
`mjx-container` of CHTML glyph boxes whose characters are CSS `::before`
content, plus a hidden MathML copy for screen readers. Each block is one
unit here:

1. MARK_EQUATIONS_JS tags every block still holding MathJax output with its
   owner - the nearest enclosing element with an id (the sentence/clause/
   table/note it belongs to) - and a key, `<owner id>.<data-node-id>`: the
   site reuses a content JSON node id for the same formula in several
   places, so the owner makes it unique. A block with no node id is
   `<owner id>.eq`; a repeat within one owner gets `-n` (the key is also
   the PNG's file name, so it stays within page_writer's safe set). Returns
   [{key, owner}] in document order; a table's pinned-column copy of a
   header cell repeats its original's key.
2. The caller screenshots each key's tight `mjx-math` glyph box once.
3. SWAP_EQUATIONS_JS replaces each `mjx-container` with an
   `<img class="equation-image">` of that PNG at the size and position the
   glyphs had, and returns the whole page's HTML - so the saved page, the
   viewer and the layout pass all show the captured image.
"""

from web_toc.parsing.page_html import ASSET_PREFIX

# Under the page asset mirror (output/web_pages/assets/), served at
# /web-assets/equations/<key>.png like every other site asset.
EQUATION_ASSET_DIR = "equations"
MARKED_SELECTOR = ".equation-block[data-equation-key]"
GLYPHS_SELECTOR = "mjx-math"

MARK_EQUATIONS_JS = """() => {
  const root = document.querySelector('main.ui-ContentPanel');
  if (!root) return [];
  const seen = new Map();
  const marked = [];
  for (const block of root.querySelectorAll('.equation-block')) {
    if (!block.querySelector('mjx-container')) continue;
    const holder = block.parentElement.closest('[id]');
    const owner = holder && root.contains(holder) ? holder.id : '';
    const base = [owner, block.dataset.nodeId || 'eq'].filter(Boolean).join('.');
    // Counted apart, so the n-th pinned copy repeats the n-th original's key.
    const pinned = !!block.closest('.table-block__table--pinned-col');
    const counter = `${pinned}|${base}`;
    seen.set(counter, (seen.get(counter) || 0) + 1);
    const n = seen.get(counter);
    const key = n === 1 ? base : `${base}-${n}`;
    block.dataset.equationKey = key;
    block.dataset.equationOwner = owner;
    marked.push({ key, owner });
  }
  return marked;
}"""

SWAP_EQUATIONS_JS = f"""() => {{
  const px = (v) => `${{Math.round(v * 100) / 100}}px`;
  for (const block of document.querySelectorAll('{MARKED_SELECTOR}')) {{
    const container = block.querySelector('mjx-container');
    const glyphs = container.querySelector('{GLYPHS_SELECTOR}') || container;
    const box = glyphs.getBoundingClientRect();
    const outer = container.getBoundingClientRect();
    const labelled = block.querySelector('[aria-label]');
    const img = document.createElement('img');
    img.className = 'equation-image';
    img.setAttribute('src',
      `{ASSET_PREFIX}/{EQUATION_ASSET_DIR}/${{block.dataset.equationKey}}.png`);
    img.alt = labelled ? labelled.getAttribute('aria-label').replace(/\\s+/g, ' ').trim() : '';
    img.dataset.equation = block.dataset.equationKey;
    img.dataset.owner = block.dataset.equationOwner;
    img.style.width = px(box.width);
    img.style.height = px(box.height);
    img.style.verticalAlign = 'middle';
    if (getComputedStyle(container).display === 'block') {{
      const style = getComputedStyle(container);
      const indent = px(box.left - outer.left);
      img.style.display = 'block';
      img.style.margin = `${{style.marginTop}} 0 ${{style.marginBottom}} ${{indent}}`;
    }}
    container.replaceWith(img);
    delete block.dataset.equationKey;
    delete block.dataset.equationOwner;
  }}
  return '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
}}"""
