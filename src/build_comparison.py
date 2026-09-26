#!/usr/bin/env python3
"""Builds output/comparison.json: a pass/fail status per unified_number,
comparing bcbc_pdf.json's text/images against bcbc_web.json's - see
src/comparison/engine.py for the rollup rules that decide each status. Text
must match exactly apart from whitespace, bold/italic included
(comparison/content_match.py); the threshold applies to images only.

Usage:
    python3 src/build_mo_toc.py      # once
    python3 src/build_web_toc.py     # once
    python3 src/build_comparison.py
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comparison.asset_loader import load_pdf_image_bytes, load_web_image_bytes
from comparison.content_match import content_matches
from comparison.engine import compare_trees
from comparison.image_similarity import DEFAULT_THRESHOLD_PERCENT, compare_images, images_match

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")


def _image_matcher(output_dir: Path, threshold_percent: float):
    def _match(pdf_image: dict, web_image: dict) -> bool:
        pdf_bytes = load_pdf_image_bytes(output_dir, pdf_image)
        web_bytes = load_web_image_bytes(output_dir, web_image)
        if pdf_bytes is None or web_bytes is None:
            return False
        result = compare_images(pdf_image.get("unified_number", ""), pdf_bytes, web_bytes)
        return images_match(result, threshold_percent)

    return _match


def run(output_dir: str, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT) -> None:
    out = Path(output_dir)
    pdf_payload = json.loads((out / "bcbc_pdf.json").read_text())
    web_json = out / "bcbc_web.json"
    web_payload = json.loads(web_json.read_text()) if web_json.exists() else None

    statuses = compare_trees(
        pdf_payload["volume"],
        pdf_payload["images"],
        web_payload["tree"] if web_payload else None,
        web_payload["images"] if web_payload else [],
        content_matches,
        _image_matcher(out, threshold_percent),
    )
    payload = {"threshold_percent": threshold_percent, "statuses": statuses}
    (out / "comparison.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--threshold-percent", type=float, default=DEFAULT_THRESHOLD_PERCENT)
    args = parser.parse_args()
    run(args.output_dir, args.threshold_percent)
    print(f"Wrote {args.output_dir}/comparison.json", file=sys.stderr)


if __name__ == "__main__":
    main()
