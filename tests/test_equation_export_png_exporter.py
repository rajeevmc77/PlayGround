from unittest.mock import MagicMock

from equation_export.domain.models import Equation
from equation_export.output.png_exporter import export_equations


def _renderer(*, fails_for: set[str] = frozenset()):
    renderer = MagicMock()

    def _render(latex, output_path):
        if latex in fails_for:
            raise ValueError(f"cannot parse {latex}")
        output_path.write_bytes(b"fakepngbytes")

    renderer.render.side_effect = _render
    return renderer


def test_writes_one_png_per_equation(tmp_path):
    equations = [Equation(id="eg001", latex="a=b"), Equation(id="eg002", latex="c=d")]

    result = export_equations(equations, _renderer(), str(tmp_path))

    assert (tmp_path / "eg001.png").read_bytes() == b"fakepngbytes"
    assert (tmp_path / "eg002.png").read_bytes() == b"fakepngbytes"
    assert result.written == ["eg001", "eg002"]
    assert result.failed == []


def test_creates_output_directory_if_missing(tmp_path):
    output_dir = tmp_path / "equations"

    export_equations([Equation(id="eg001", latex="a=b")], _renderer(), str(output_dir))

    assert (output_dir / "eg001.png").exists()


def test_render_failure_is_skipped_not_fatal(tmp_path):
    equations = [
        Equation(id="eg001", latex="good"),
        Equation(id="eg002", latex="bad"),
        Equation(id="eg003", latex="also-good"),
    ]

    result = export_equations(equations, _renderer(fails_for={"bad"}), str(tmp_path))

    assert result.written == ["eg001", "eg003"]
    assert result.failed == ["eg002"]
    assert not (tmp_path / "eg002.png").exists()


def test_empty_list_writes_nothing(tmp_path):
    result = export_equations([], _renderer(), str(tmp_path))

    assert result.written == []
    assert result.failed == []


def test_render_is_called_with_each_equations_latex_and_target_path(tmp_path):
    export_equations([Equation(id="eg001", latex="x=y")], (renderer := _renderer()), str(tmp_path))

    renderer.render.assert_called_once_with("x=y", tmp_path / "eg001.png")


def _mathml_fallback(*, fails_for: set[str] = frozenset()):
    fallback = MagicMock()

    def _render(mathml, output_path):
        if mathml in fails_for:
            raise ValueError(f"MathJax could not typeset {mathml}")
        output_path.write_bytes(b"fakemathjaxpng")

    fallback.render.side_effect = _render
    return fallback


def test_equation_needing_fallback_skips_the_primary_renderer_entirely(tmp_path):
    equation = Equation(id="eg001", latex="N\n^\n", mathml="<math><mi>N</mi></math>")
    primary = _renderer()
    fallback = _mathml_fallback()

    result = export_equations([equation], primary, str(tmp_path), fallback_renderer=fallback)

    primary.render.assert_not_called()
    fallback.render.assert_called_once_with("<math><mi>N</mi></math>", tmp_path / "eg001.png")
    assert result.written == ["eg001"]


def test_primary_failure_falls_back_to_mathml_when_available(tmp_path):
    equation = Equation(id="eg002", latex="bad", mathml="<math><mi>Q</mi></math>")
    primary = _renderer(fails_for={"bad"})
    fallback = _mathml_fallback()

    result = export_equations([equation], primary, str(tmp_path), fallback_renderer=fallback)

    fallback.render.assert_called_once_with("<math><mi>Q</mi></math>", tmp_path / "eg002.png")
    assert result.written == ["eg002"]
    assert result.failed == []


def test_successful_primary_render_never_invokes_fallback(tmp_path):
    equation = Equation(id="eg001", latex="a=b", mathml="<math><mi>a</mi></math>")
    fallback = _mathml_fallback()

    export_equations([equation], _renderer(), str(tmp_path), fallback_renderer=fallback)

    fallback.render.assert_not_called()


def test_failure_with_no_fallback_available_is_still_skipped_not_fatal(tmp_path):
    equation = Equation(id="eg002", latex="bad", mathml=None)
    primary = _renderer(fails_for={"bad"})

    result = export_equations(
        [equation], primary, str(tmp_path), fallback_renderer=_mathml_fallback()
    )

    assert result.written == []
    assert result.failed == ["eg002"]
    assert not (tmp_path / "eg002.png").exists()


def test_fallback_renderer_defaults_to_none_and_failures_still_skip(tmp_path):
    equation = Equation(id="eg002", latex="bad")

    result = export_equations([equation], _renderer(fails_for={"bad"}), str(tmp_path))

    assert result.failed == ["eg002"]
