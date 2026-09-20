#!/usr/bin/env python3
"""
Extracts each Figure's source image from "bcbc_2024.pdf", matched to its
caption, for future visual similarity comparison (including against the
MO Package extraction from `extract_figures.py` - both documents share the
same underlying Figure content).

Reads the Figure index already produced by `bcbc2024_index.py`
(output/bcbc2024_index.json) and, for each entry, locates its image.

Why this needs different logic than `extract_figures.py`
----------------------------------------------------------
Confirmed by direct inspection: unlike the MO Package (where every Figure
is a raster image), only 21 of this PDF's 160 Figure-caption pages have
any embedded raster image at all - the rest (139 pages) are native PDF
vector drawings with no raster image to extract via xref. So each Figure
is resolved in two stages:

  1. Raster match (same algorithm as `extract_figures.py`, adapted to this
     PDF's own font names): nearest unclaimed raster image above the
     caption on the same page; else below it on the same page; else an
     unclaimed image carried over from the previous page (confirmed same
     page-break wrinkle as the MO Package).
  2. Vector-region crop, when no raster image resolves: confirmed both of
     the MO Package's caption/image orderings recur here (caption above
     the diagram, e.g. "Figure 4.1.7.6.-A" on page 549; caption below it,
     e.g. "Figure A-1.1.1.1.(6)" on page 58) - and this PDF gives no font
     or layout signal for which applies to a given caption. What is
     reliable: the vertical gap on whichever side holds the diagram is
     far larger (up to ~450pt, confirmed) than an ordinary paragraph-to-
     paragraph gap (a few pt), so the larger of the two candidate gaps
     (before the caption block vs. after it) is rendered as a bitmap via
     `page.get_pixmap(clip=...)`, which captures vector art the same way
     regardless of how it was drawn. A gap barely bigger than normal
     spacing on both sides means there's no diagram to find (confirmed
     real: see the MO Package's own "Figure A-4.1.7.5.(4)", a caption
     with literally no adjacent image or vector art) - left unresolved
     rather than guessed at.

Outputs
-------
- output/figures_2024/<identifier>_p<page>.<ext>  - the extracted images
- output/bcbc2024_index_figures.json - full metadata (image_path, pixel
  size, perceptual hash, and which of the two stages resolved it)
- output/bcbc2024_index_figures.md   - human-readable report with
  inline thumbnails
"""

import json
import sys
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bcbc2024_index as idx2  # noqa: E402  (path insert must come first)
from extract_figures import _phash, _safe_stem  # noqa: E402

MIN_IMAGE_DIM = 40  # pt; same floor as extract_figures.py - excludes inline icons
MIN_VECTOR_GAP = 30  # pt; well above ordinary paragraph spacing, well below a real diagram's
FIGURES_DIR = idx2.PROJECT_ROOT / "output" / "figures_2024"
JSON_OUT = str(idx2.PROJECT_ROOT / "output" / "bcbc2024_index_figures.json")
MD_OUT = str(idx2.PROJECT_ROOT / "output" / "bcbc2024_index_figures.md")


def _page_lines(page):
    """Like bcbc2024_index._page_lines, but keeps each line's own bottom
    edge (y1) too - needed to bound the gap around a caption precisely,
    rather than approximating a fixed line-height buffer.
    """
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            fonts = {s["font"] for s in spans}
            font = fonts.pop() if len(fonts) == 1 else "/".join(sorted(fonts))
            x0, y0, _x1, y1 = line["bbox"]
            lines.append({"y0": y0, "y1": y1, "x0": x0, "text": text, "font": font})
    lines.sort(key=lambda l: (l["y0"], l["x0"]))
    return lines


def _is_caption_continuation(line, row_ys):
    return ("Bold" in line["font"] and "Blk" not in line["font"]
            and not idx2.RE_CAPTION.match(line["text"])
            and not idx2.RE_FORMING_PART.match(line["text"])
            and not idx2.RE_NOTES_TO_CAPTION.match(line["text"])
            and round(line["y0"], 1) not in row_ys)


def _consume_caption_block(lines, i, row_ys):
    """Index of the line after this caption's own title (up to 2
    continuation lines, mirroring scan_pages' own cap) and optional
    "Forming Part of ..." line.

    Confirmed on page 530/559: a "Forming Part of ..." line can itself be
    duplicate-rendered as several overlapping fragments sharing one y0
    and font ("For" / "orming P" / "ming Par" / ... all
    HelveticaLTStd-Roman at the same height) - the same font-mixing
    artifact bcbc2024_index.py notes elsewhere. Once the first
    forming-part fragment is recognized, skip every immediately-following
    line that shares BOTH its y0 and its font (the same rendered text
    repeated, not new content) - gated on that first match so this never
    fires on an ordinary two-line heading pair, which routinely shares
    one y0 too (confirmed: "D-2.3.11." + "Ceiling Membrane Openings..."
    both at y=650.1 on page 815) and must NOT be treated as noise.
    """
    j = i + 1
    while j < len(lines) and j - i <= 2 and _is_caption_continuation(lines[j], row_ys):
        j += 1
    if j < len(lines) and idx2.RE_FORMING_PART.match(lines[j]["text"]):
        y0, font = round(lines[j]["y0"], 1), lines[j]["font"]
        while j < len(lines) and round(lines[j]["y0"], 1) == y0 and lines[j]["font"] == font:
            j += 1
    return j


def _figure_regions(doc):
    """(page0, caption_y0, prev_bottom, caption_top, block_bottom,
    next_top) for every genuine Figure caption, in document order -
    prev_bottom/caption_top bound the gap if the diagram precedes the
    caption; block_bottom/next_top bound the gap if it follows.
    """
    regions = []
    for pno in range(doc.page_count):
        lines = _page_lines(doc[pno])
        flat = [(l["y0"], l["x0"], l["text"], l["font"]) for l in lines]
        row_ys = idx2._multi_column_rows(flat)
        page_h = doc[pno].rect.height

        i = 0
        while i < len(lines):
            line = lines[i]
            cap_m = idx2.RE_CAPTION.match(line["text"])
            if not (cap_m and "Bold" in line["font"] and "Blk" not in line["font"]):
                i += 1
                continue
            j = _consume_caption_block(lines, i, row_ys)
            if cap_m.group(1) == "Figure":
                regions.append({
                    "page0": pno, "caption_y0": line["y0"],
                    "prev_bottom": lines[i - 1]["y1"] if i > 0 else 0.0,
                    "caption_top": line["y0"],
                    "block_bottom": lines[j - 1]["y1"],
                    "next_top": lines[j]["y0"] if j < len(lines) else page_h,
                })
            i = j
    return regions


def _page_images(page, min_dim=MIN_IMAGE_DIM):
    images = []
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        if min(x1 - x0, y1 - y0) < min_dim:
            continue
        images.append({"bbox": (x0, y0, x1, y1), "xref": info["xref"], "claimed": False})
    images.sort(key=lambda im: im["bbox"][1])
    return images


def _match_raster(caption_y0, page_images, pending_images):
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

    return None, None


def _crop_region(page, top, bottom, margin=4):
    top, bottom = max(top, 0.0), min(bottom, page.rect.height)
    if bottom - top < MIN_VECTOR_GAP:
        return None
    rect = fitz.Rect(page.rect.x0 + margin, top, page.rect.x1 - margin, bottom)
    pix = page.get_pixmap(clip=rect, dpi=200)
    return pix.tobytes("png"), pix.width, pix.height


def _render_vector_region(page, region):
    gap_before = region["caption_top"] - region["prev_bottom"]
    gap_after = region["next_top"] - region["block_bottom"]
    if gap_before >= gap_after:
        cropped = _crop_region(page, region["prev_bottom"], region["caption_top"])
        source = "vector_before"
    else:
        cropped = _crop_region(page, region["block_bottom"], region["next_top"])
        source = "vector_after"
    return (*cropped, source) if cropped else (None, None, None, "unresolved")


def _save(data, ext, stem):
    path = FIGURES_DIR / f"{stem}.{ext}"
    path.write_bytes(data)
    return path


def extract_figures(pdf_path, figures):
    doc = fitz.open(pdf_path)
    regions = _figure_regions(doc)
    if len(regions) != len(figures):
        print(f"warning: {len(regions)} detected captions vs {len(figures)} indexed "
              f"figures - position-based matching may drift", file=sys.stderr)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    current_pno, page_images, pending_images = None, [], []

    for region, fig in zip(regions, figures):
        page0 = region["page0"]
        if page0 != current_pno:
            pending_images = [im for im in page_images if not im["claimed"]]
            page_images = _page_images(doc[page0])
            current_pno = page0

        image, source = _match_raster(region["caption_y0"], page_images, pending_images)
        stem = _safe_stem(fig["identifier"], fig["page"])
        record = dict(fig)

        if image is not None:
            info = doc.extract_image(image["xref"])
            path = _save(info["image"], info["ext"], stem)
            raw, w, h = info["image"], info["width"], info["height"]
        else:
            raw, w, h, source = _render_vector_region(doc[page0], region)
            path = _save(raw, "png", stem) if raw else None

        record["match_source"] = source
        record.update(
            image_path=str(path.relative_to(idx2.PROJECT_ROOT / "output")) if path else None,
            image_width=w, image_height=h, phash=_phash(raw) if raw else None,
        )
        records.append(record)

    return records


def write_json(records, out_path):
    Path(out_path).write_text(json.dumps(records, indent=2))


def write_markdown(records, out_path):
    resolved = sum(1 for r in records if r["image_path"])
    lines = [
        "# bcbc_2024 - Figure Image Extraction",
        "",
        f"{resolved} / {len(records)} figures matched to an extracted image.",
        "",
    ]

    unresolved = [r for r in records if not r["image_path"]]
    if unresolved:
        lines.append("## Unresolved (no image or vector art found)")
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


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else idx2.DEFAULT_PDF
    json_path = sys.argv[2] if len(sys.argv) > 2 else idx2.JSON_OUT
    if not Path(pdf_path).exists():
        sys.exit(f"No such file: {pdf_path}")
    if not Path(json_path).exists():
        sys.exit(f"No such file: {json_path} (run bcbc2024_index.py first)")

    figures = json.loads(Path(json_path).read_text())["figures"]
    print(f"Matching {len(figures)} figure captions to images...", file=sys.stderr)
    records = extract_figures(pdf_path, figures)

    write_json(records, JSON_OUT)
    write_markdown(records, MD_OUT)

    resolved = sum(1 for r in records if r["image_path"])
    print(f"Extracted {resolved}/{len(records)} figure images -> {FIGURES_DIR}", file=sys.stderr)
    print(f"Wrote {JSON_OUT} and {MD_OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
