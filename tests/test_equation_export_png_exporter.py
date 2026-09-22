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
