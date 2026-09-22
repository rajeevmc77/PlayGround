import sys
from pathlib import Path

from equation_export.domain.models import Equation, ExportResult, equation_needs_mathml_fallback
from equation_export.rendering.latex_renderer import LatexRenderer
from equation_export.rendering.mathjax_renderer import MathmlRenderer


def export_equations(
    equations: list[Equation],
    renderer: LatexRenderer,
    output_dir: str,
    fallback_renderer: MathmlRenderer | None = None,
) -> ExportResult:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ExportResult()
    for equation in equations:
        _render_one(equation, renderer, fallback_renderer, out_dir, result)
    return result


def _render_one(
    equation: Equation,
    renderer: LatexRenderer,
    fallback_renderer: MathmlRenderer | None,
    out_dir: Path,
    result: ExportResult,
) -> None:
    target = out_dir / f"{equation.id}.png"
    if _render(equation, renderer, fallback_renderer, target):
        result.written.append(equation.id)
        return
    print(f"  skipped equation {equation.id} (render failed)", file=sys.stderr)
    result.failed.append(equation.id)


def _render(
    equation: Equation,
    renderer: LatexRenderer,
    fallback_renderer: MathmlRenderer | None,
    target: Path,
) -> bool:
    if equation_needs_mathml_fallback(equation):
        return _try_render(fallback_renderer, equation.mathml, target)
    if _try_render(renderer, equation.latex, target):
        return True
    return _try_render(fallback_renderer, equation.mathml, target)


def _try_render(renderer, source: str | None, target: Path) -> bool:
    if renderer is None or source is None:
        return False
    try:
        renderer.render(source, target)
        return True
    except ValueError:
        return False
