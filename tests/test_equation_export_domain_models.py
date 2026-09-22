from equation_export.domain.models import (
    Equation,
    ExportResult,
    equation_needs_mathml_fallback,
)


def test_equation_holds_id_and_latex():
    eq = Equation(id="es000562q1", latex="A_{C}=A+(A_{F}\\times F_{EO})")
    assert eq.id == "es000562q1"
    assert eq.latex == "A_{C}=A+(A_{F}\\times F_{EO})"


def test_equation_mathml_defaults_to_none():
    eq = Equation(id="es000562q1", latex="A_{C}=A+(A_{F}\\times F_{EO})")
    assert eq.mathml is None


def test_equation_holds_optional_mathml():
    eq = Equation(id="eg02520a", latex="N", mathml="<math><mi>N</mi></math>")
    assert eq.mathml == "<math><mi>N</mi></math>"


def test_needs_mathml_fallback_when_latex_has_embedded_newline_and_mathml_present():
    eq = Equation(id="eg02520a", latex="N\n^\n", mathml="<math><mi>N</mi></math>")
    assert equation_needs_mathml_fallback(eq) is True


def test_does_not_need_fallback_for_single_line_latex():
    eq = Equation(id="es000562q1", latex="A_{C}=A", mathml="<math><mi>A</mi></math>")
    assert equation_needs_mathml_fallback(eq) is False


def test_does_not_need_fallback_when_mathml_is_missing():
    eq = Equation(id="eg02520a", latex="N\n^\n", mathml=None)
    assert equation_needs_mathml_fallback(eq) is False


def test_export_result_defaults_to_empty_lists():
    result = ExportResult()
    assert result.written == []
    assert result.failed == []


def test_export_result_lists_are_independent_between_instances():
    a = ExportResult()
    b = ExportResult()
    a.written.append("eg001")
    assert b.written == []
