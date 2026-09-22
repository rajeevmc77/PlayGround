#!/usr/bin/env python3
"""Fetches the live BC Building Code website's equation-map.json and renders
every equation's LaTeX source to a standalone PNG in output/equations/.

A handful of equations flatten their visual layout into raw newlines and bare
accent characters instead of valid LaTeX (see
`equation_export.domain.models.equation_needs_mathml_fallback`); those are
rendered from their `mathml` field via a headless-browser MathJax typeset
instead, matching what the live site itself displays.

Usage:
    python3 src/export_equations.py
    python3 src/export_equations.py --base-url https://dev.buildingcode.gov.bc.ca --version 2024

The MathJax fallback needs a Chromium binary, installed once via:
    ./venv/bin/playwright install chromium
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from equation_export.output.png_exporter import export_equations
from equation_export.parsing.equation_source import HttpxEquationSource
from equation_export.rendering.latex_renderer import MatplotlibLatexRenderer
from equation_export.rendering.mathjax_renderer import MathJaxRenderer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://dev.buildingcode.gov.bc.ca"
DEFAULT_VERSION = "2024"
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output" / "equations")


async def _fetch_equations(base_url: str, version: str):
    async with HttpxEquationSource(base_url, version) as source:
        return await source.fetch_equations()


def run(base_url: str, version: str, output_dir: str) -> None:
    # Playwright's sync API refuses to run inside an active asyncio event
    # loop, so the async httpx fetch must finish (and its loop close) before
    # the MathJax fallback renderer starts.
    equations = asyncio.run(_fetch_equations(base_url, version))
    with MathJaxRenderer() as fallback_renderer:
        result = export_equations(
            equations, MatplotlibLatexRenderer(), output_dir, fallback_renderer
        )
    print(f"Wrote {len(result.written)} PNGs, {len(result.failed)} failed", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(f"Fetching {args.base_url} equation map (version {args.version}) ...", file=sys.stderr)
    run(args.base_url, args.version, args.output_dir)
    print(f"Wrote {args.output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
