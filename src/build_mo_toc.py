#!/usr/bin/env python3
"""Parses MO Package BCBC MRK signed.pdf into output/mo_toc.json + output/mo_toc.md
and every embedded image's thumbnail under output/thumbnails/.

Usage:
    python3 src/build_mo_toc.py                # uses data/<default PDF>
    python3 src/build_mo_toc.py /path/to/other.pdf
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mo_toc.output.json_writer import write_json
from mo_toc.output.markdown_writer import write_markdown
from mo_toc.output.thumbnail_writer import write_thumbnails
from mo_toc.parsing.image_extractor import extract_images
from mo_toc.parsing.pdf_source import PyMuPdfSource
from mo_toc.parsing.tree_builder import build_tree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = str(PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf")
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def run(pdf_path: str, output_dir: str) -> None:
    source = PyMuPdfSource(pdf_path)
    volume, captions = build_tree(source)
    raw_images = extract_images(source)
    images = write_thumbnails(raw_images, str(Path(output_dir) / "thumbnails"))
    write_json(volume, captions, images, str(Path(output_dir) / "mo_toc.json"))
    write_markdown(volume, captions, str(Path(output_dir) / "mo_toc.md"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pdf_path", nargs="?", default=DEFAULT_PDF)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    if not Path(args.pdf_path).exists():
        sys.exit(f"No such file: {args.pdf_path}")
    print(f"Parsing {args.pdf_path} ...", file=sys.stderr)
    run(args.pdf_path, args.output_dir)
    print(f"Wrote {args.output_dir}/mo_toc.json, mo_toc.md, thumbnails/", file=sys.stderr)


if __name__ == "__main__":
    main()
