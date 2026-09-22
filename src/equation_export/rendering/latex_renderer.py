from pathlib import Path
from typing import Protocol

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

FONT_SIZE = 20


class LatexRenderer(Protocol):
    def render(self, latex: str, output_path: Path) -> None: ...


class MatplotlibLatexRenderer:
    """Renders a LaTeX/mathtext string to a standalone PNG via matplotlib's
    mathtext engine. Malformed LaTeX (the site's equation data has a few glued
    commands like `\\timesLD`) raises ValueError instead of writing a file, so
    the caller can skip that one equation without losing the rest of a batch."""

    def render(self, latex: str, output_path: Path) -> None:
        fig = plt.figure(figsize=(0.01, 0.01))
        try:
            fig.text(0, 0, f"${latex}$", fontsize=FONT_SIZE)
            fig.savefig(output_path, dpi=300, transparent=True, bbox_inches="tight", pad_inches=0.1)
        finally:
            plt.close(fig)
