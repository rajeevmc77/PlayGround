#!/usr/bin/env python3
"""Compares same-figure images kept in compare-images/pdf/ (PNGs rendered
from the MO Package PDF) against compare-images/web/ (JPEGs downloaded from
the live BC Building Code website), matching filenames by stem regardless of
extension and scoring each matched pair by perceptual-hash similarity.

Usage:
    python3 src/compare_images.py
    python3 src/compare_images.py --pdf-dir path/to/pdf --web-dir path/to/web
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_compare.analysis.similarity import compare
from image_compare.domain.models import ComparisonResult, PairingResult
from image_compare.parsing.autocrop import autocrop_to_content
from image_compare.parsing.pair_finder import find_pairs
from image_compare.parsing.phash import compute_phash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF_DIR = PROJECT_ROOT / "compare-images" / "pdf"
DEFAULT_WEB_DIR = PROJECT_ROOT / "compare-images" / "web"


def _visible_filenames(directory: Path) -> list[str]:
    return [entry.name for entry in directory.iterdir() if not entry.name.startswith(".")]


def build_comparison(pdf_dir: Path, web_dir: Path) -> tuple[PairingResult, list[ComparisonResult]]:
    pairing = find_pairs(_visible_filenames(pdf_dir), _visible_filenames(web_dir))
    results = [
        compare(
            pair.stem,
            compute_phash(autocrop_to_content((pdf_dir / pair.pdf_filename).read_bytes())),
            compute_phash(autocrop_to_content((web_dir / pair.web_filename).read_bytes())),
        )
        for pair in pairing.matched
    ]
    return pairing, results


def format_report(pairing: PairingResult, results: list[ComparisonResult]) -> str:
    lines = ["Matched pairs:"]
    if not results:
        lines.append("  none")
    for result in results:
        lines.append(
            f"  {result.stem}  {result.similarity_percent}%  (distance {result.hash_distance}/64)"
        )
    lines.append("")
    lines.append(f"Unmatched (pdf only): {', '.join(pairing.pdf_only) or 'none'}")
    lines.append(f"Unmatched (web only): {', '.join(pairing.web_only) or 'none'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--web-dir", type=Path, default=DEFAULT_WEB_DIR)
    args = parser.parse_args()
    pairing, results = build_comparison(args.pdf_dir, args.web_dir)
    print(format_report(pairing, results))


if __name__ == "__main__":
    main()
