#!/usr/bin/env python3
"""
Extracts each Figure's source image from "MO Package BCBC MRK signed.pdf",
matched to its caption for future visual similarity comparison.

Reads the Figure index already produced by `bcbc_mo_index.py`
(output/bcbc_mo_index.json) and, for each entry, locates the raster image
its "Figure <citation>" caption belongs to.

How matching works
-------------------
Confirmed by direct inspection: every genuine Figure is a raster image
(not vector art) sitting immediately above its caption in reading order.
Two wrinkles ruled this out from being a simple "same page, same order"
join:

  - Not every image on a page is a Figure - the PDF also embeds cover/
    letterhead logos, inline glyphs/checkboxes inside body text and
    tables, and administrative form graphics (the "Schedule A" permit
    forms near the end of the document). These are filtered out by a
    minimum on-page size (confirmed noise images are under 30x30pt;
    confirmed real figures are all well over 100pt in both dimensions).
  - A figure's image and its caption can straddle a page break: the
    image renders at the very bottom of one page and its caption prints
    at the top of the next (confirmed on pages 414-415, where the third
    of three images on page 414 has no on-page caption - its caption,
    "Figure A-3.2.3.14.(1)-C", is the first line of page 415). So each
    page carries forward its own unclaimed images for the next page's
    first caption(s) to claim.

For each page, in caption order: prefer the nearest not-yet-claimed
image whose bottom edge sits above the caption on the same page; if
none, fall back to an unclaimed image carried over from the previous
page; otherwise the figure is reported unresolved rather than guessed.

Outputs
-------
- output/figures/<identifier>_p<page>.<ext>  - the extracted image files
- output/bcbc_mo_index_figures.json - full metadata (for programmatic
  similarity comparison: image_path, pixel size, perceptual hash)
- output/bcbc_mo_index_figures.md   - human-readable report with inline
  thumbnails
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bcbc_mo_index as idx  # noqa: E402  (path insert must come first)

MIN_IMAGE_DIM = 40  # pt; excludes inline glyph/checkbox icons, confirmed <30x30
FIGURES_DIR = idx.PROJECT_ROOT / "output" / "figures"
JSON_OUT = str(idx.PROJECT_ROOT / "output" / "bcbc_mo_index_figures.json")
MD_OUT = str(idx.PROJECT_ROOT / "output" / "bcbc_mo_index_figures.md")


def _figure_caption_positions(doc):
    """(page0, y0) for every genuine Figure caption, in document order -
    same font-gated RE_CAPTION match build_index() uses. Only the
    caption's own first line is needed here (not its full title), so
    unlike build_index() this doesn't consume continuation lines.
    """
    positions = []
    for pno in range(doc.page_count):
        for y0, _x0, text, font in idx._page_lines(doc[pno]):
            m = idx.RE_CAPTION.match(text)
            is_caption = m and "Bold" in font and "Black" not in font and "Narrow" not in font
            if is_caption and m.group(1) == "Figure":
                positions.append((pno, y0))
    return positions


def _page_images(page, min_dim=MIN_IMAGE_DIM):
    images = []
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        if min(x1 - x0, y1 - y0) < min_dim:
            continue
        images.append({"bbox": (x0, y0, x1, y1), "xref": info["xref"], "claimed": False})
    images.sort(key=lambda im: im["bbox"][1])
    return images


def _match_image(caption_y0, page_images, pending_images):
    """Most captions sit below their image; a few pages (confirmed: the
    Part 4 structural-load figures, e.g. "Figure 4.1.6.5.-A") instead
    print the caption above it. Prefer the nearest unclaimed image above
    the caption (the common case, and the only one confirmed to cross a
    page break); only look below on the same page if nothing qualifies
    above; only reach into the previous page's leftovers as a last
    resort, since the below-caption layout has never been seen crossing
    a page break.
    """
    above = [im for im in page_images if not im["claimed"] and im["bbox"][3] <= caption_y0 + 2]
    if above:
        im = max(above, key=lambda im: im["bbox"][3])
        im["claimed"] = True
        return im, "same_page_above"

    below = [im for im in page_images if not im["claimed"] and im["bbox"][1] >= caption_y0 - 2]
    if below:
        im = min(below, key=lambda im: im["bbox"][1])
        im["claimed"] = True
        return im, "same_page_below"

    for im in pending_images:
        if not im["claimed"]:
            im["claimed"] = True
            return im, "previous_page"

    return None, "unresolved"


def _safe_stem(identifier, page):
    safe = re.sub(r"[^A-Za-z0-9.\-]+", "_", identifier).strip("_")
    return f"{safe}_p{page}"


def _phash(image_bytes):
    from PIL import Image
    import imagehash

    try:
        return str(imagehash.phash(Image.open(io.BytesIO(image_bytes))))
    except Exception:
        return None


def _save_image(doc, xref, stem):
    info = doc.extract_image(xref)
    path = FIGURES_DIR / f"{stem}.{info['ext']}"
    path.write_bytes(info["image"])
    return path, info["width"], info["height"], info["image"], _phash(info["image"])


def extract_figures(pdf_path, figures):
    doc = fitz.open(pdf_path)
    positions = _figure_caption_positions(doc)
    if len(positions) != len(figures):
        print(f"warning: {len(positions)} detected captions vs {len(figures)} indexed "
              f"figures - position-based matching may drift", file=sys.stderr)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    current_pno, page_images, pending_images = None, [], []

    for (page0, y0), fig in zip(positions, figures):
        if page0 != current_pno:
            pending_images = [im for im in page_images if not im["claimed"]]
            page_images = _page_images(doc[page0])
            current_pno = page0

        image, source = _match_image(y0, page_images, pending_images)
        record = dict(fig, match_source=source)
        if image is None:
            record.update(image_path=None, image_width=None, image_height=None, phash=None)
        else:
            stem = _safe_stem(fig["identifier"], fig["page"])
            path, w, h, _raw, phash = _save_image(doc, image["xref"], stem)
            record.update(
                image_path=str(path.relative_to(idx.PROJECT_ROOT / "output")),
                image_width=w, image_height=h, phash=phash,
            )
        records.append(record)

    return records


def write_json(records, out_path):
    Path(out_path).write_text(json.dumps(records, indent=2))


def write_markdown(records, out_path):
    resolved = sum(1 for r in records if r["image_path"])
    lines = [
        "# BCBC MO Package - Figure Image Extraction",
        "",
        f"{resolved} / {len(records)} figures matched to an extracted image.",
        "",
    ]

    unresolved = [r for r in records if not r["image_path"]]
    if unresolved:
        lines.append("## Unresolved (no image match found)")
        lines.append("")
        for r in unresolved:
            lines.append(f"- `{r['identifier']}` (page {r['page']}) - {r['title']}")
        lines.append("")

    lines += [
        "## Figure Index",
        "",
        "| # | Identifier | Title | Owner | Page | Match | Image | Size (px) | pHash |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(records, 1):
        img_cell = f"![]({r['image_path']})" if r["image_path"] else "-"
        size = f"{r['image_width']}x{r['image_height']}" if r["image_path"] else "-"
        lines.append(
            f"| {i} | {r['identifier']} | {r['title']} | {r.get('owner_citation', '')} | "
            f"{r['page']} | {r['match_source']} | {img_cell} | {size} | `{r['phash'] or '-'}` |"
        )

    Path(out_path).write_text("\n".join(lines))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pdf_path", nargs="?", default=idx.DEFAULT_PDF,
                        help=f"PDF to extract figures from (default: {idx.DEFAULT_PDF})")
    parser.add_argument("json_path", nargs="?", default=idx.JSON_OUT,
                        help=f"Figure index JSON to read (default: {idx.JSON_OUT})")
    return parser.parse_args()


def main():
    args = parse_args()
    if not Path(args.pdf_path).exists():
        sys.exit(f"No such file: {args.pdf_path}")
    if not Path(args.json_path).exists():
        sys.exit(f"No such file: {args.json_path} (run bcbc_mo_index.py first)")

    figures = json.loads(Path(args.json_path).read_text())["figures"]
    print(f"Matching {len(figures)} figure captions to page images...", file=sys.stderr)
    records = extract_figures(args.pdf_path, figures)

    write_json(records, JSON_OUT)
    write_markdown(records, MD_OUT)

    resolved = sum(1 for r in records if r["image_path"])
    print(f"Extracted {resolved}/{len(records)} figure images -> {FIGURES_DIR}", file=sys.stderr)
    print(f"Wrote {JSON_OUT} and {MD_OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
