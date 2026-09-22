from unittest.mock import AsyncMock, MagicMock, patch

from equation_export.domain.models import Equation, ExportResult
from export_equations import run


def _mock_source(mock_source_cls):
    mock_source = AsyncMock()
    mock_source_cls.return_value = mock_source
    mock_source.__aenter__.return_value = mock_source
    return mock_source


def _mock_mathjax_renderer(mock_mathjax_cls):
    mock_renderer = MagicMock()
    mock_mathjax_cls.return_value.__enter__.return_value = mock_renderer
    return mock_renderer


@patch("export_equations.export_equations")
@patch("export_equations.MathJaxRenderer")
@patch("export_equations.HttpxEquationSource")
def test_run_fetches_equations_and_exports_them(
    mock_source_cls, mock_mathjax_cls, mock_export, tmp_path, capsys
):
    mock_source = _mock_source(mock_source_cls)
    mock_fallback = _mock_mathjax_renderer(mock_mathjax_cls)
    equations = [Equation(id="eg001", latex="a=b")]
    mock_source.fetch_equations.return_value = equations
    mock_export.return_value = ExportResult(written=["eg001"], failed=[])

    run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path))

    mock_source_cls.assert_called_once_with("https://dev.buildingcode.gov.bc.ca", "2024")
    mock_source.fetch_equations.assert_called_once()
    args, _ = mock_export.call_args
    assert args[0] == equations
    assert args[2] == str(tmp_path)
    assert args[3] is mock_fallback
    assert "Wrote 1 PNGs, 0 failed" in capsys.readouterr().err


@patch("export_equations.export_equations")
@patch("export_equations.MathJaxRenderer")
@patch("export_equations.HttpxEquationSource")
def test_run_reports_failures_in_the_summary(
    mock_source_cls, mock_mathjax_cls, mock_export, tmp_path, capsys
):
    mock_source = _mock_source(mock_source_cls)
    _mock_mathjax_renderer(mock_mathjax_cls)
    mock_source.fetch_equations.return_value = []
    mock_export.return_value = ExportResult(written=[], failed=["eg002"])

    run("https://dev.buildingcode.gov.bc.ca", "2024", str(tmp_path))

    assert "Wrote 0 PNGs, 1 failed" in capsys.readouterr().err
