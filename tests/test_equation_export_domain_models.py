from equation_export.domain.models import Equation, ExportResult


def test_equation_holds_id_and_latex():
    eq = Equation(id="es000562q1", latex="A_{C}=A+(A_{F}\\times F_{EO})")
    assert eq.id == "es000562q1"
    assert eq.latex == "A_{C}=A+(A_{F}\\times F_{EO})"


def test_export_result_defaults_to_empty_lists():
    result = ExportResult()
    assert result.written == []
    assert result.failed == []


def test_export_result_lists_are_independent_between_instances():
    a = ExportResult()
    b = ExportResult()
    a.written.append("eg001")
    assert b.written == []
