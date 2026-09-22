import sys
from pathlib import Path

from equation_export.domain.models import Equation, ExportResult
from equation_export.rendering.latex_renderer import LatexRenderer


def export_equations(
    equations: list[Equation], renderer: LatexRenderer, output_dir: str
) -> ExportResult:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ExportResult()
    for equation in equations:
        _render_one(equation, renderer, out_dir, result)
    return result


def _render_one(equation: Equation, renderer: LatexRenderer, out_dir: Path, result: ExportResult):
    target = out_dir / f"{equation.id}.png"
    try:
        renderer.render(equation.latex, target)
    except ValueError:
        print(f"  skipped equation {equation.id} (render failed)", file=sys.stderr)
        result.failed.append(equation.id)
        return
    result.written.append(equation.id)
