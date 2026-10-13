from web_toc.domain.models import EquationCapture, EquationSource, MarkedEquation


def test_equation_source_defaults_mathml_to_none():
    source = EquationSource(latex="x^2")
    assert source.mathml is None


def test_marked_equation_holds_key_and_node_id():
    marked = MarkedEquation(key="p3.es1", node_id="es1")
    assert (marked.key, marked.node_id) == ("p3.es1", "es1")


def test_equation_capture_holds_html_and_marked_equations():
    capture = EquationCapture(html="<html></html>", marked=[MarkedEquation("p3.es1", "es1")])
    assert capture.marked[0].key == "p3.es1"
