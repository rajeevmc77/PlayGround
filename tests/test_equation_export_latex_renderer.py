import pytest

from equation_export.rendering.latex_renderer import MatplotlibLatexRenderer


def test_render_writes_a_png_file(tmp_path):
    target = tmp_path / "eq.png"
    MatplotlibLatexRenderer().render(r"V_{sp}=0.9S_a(0.2,X_{450})F_sI_EW_p", target)
    assert target.exists()
    assert target.read_bytes().startswith(b"\x89PNG")


def test_render_raises_value_error_for_malformed_latex(tmp_path):
    target = tmp_path / "eq.png"
    with pytest.raises(ValueError):
        MatplotlibLatexRenderer().render(r"Area=0.24(2\timesLD-1.2)^{2}", target)
    assert not target.exists()
