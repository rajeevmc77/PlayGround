from dataclasses import dataclass, field


@dataclass
class Equation:
    id: str
    latex: str
    mathml: str | None = None


@dataclass
class ExportResult:
    written: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def equation_needs_mathml_fallback(equation: Equation) -> bool:
    """The site's own latex export sometimes flattens a diacritic-heavy symbol's
    visual layout into raw newlines and bare accent characters (e.g. a hat drawn
    on its own line) instead of valid TeX - matplotlib's mathtext parser accepts
    this input without error but draws it as literal garbage text. An embedded
    newline is a reliable signal that latex isn't trustworthy here, so equations
    with one are routed to the mathml field instead, which is what the site's
    own MathJax rendering already relies on."""
    return equation.mathml is not None and "\n" in equation.latex
