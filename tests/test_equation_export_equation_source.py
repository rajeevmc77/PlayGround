import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from equation_export.parsing.equation_source import HttpxEquationSource


def _fake_response(payload: dict):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _run(coro):
    return asyncio.run(coro)


def _mock_client(mock_client_cls):
    mock_client = AsyncMock()
    mock_client_cls.return_value = mock_client
    return mock_client


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_requests_the_correct_url(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response({})

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    _run(scenario())

    mock_client.get.assert_called_once_with(
        "https://dev.buildingcode.gov.bc.ca/data/2024/equation-map.json"
    )


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_maps_each_entry_to_an_equation(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response(
        {
            "eg02500a": {"id": "eg02500a", "latex": "Area=0.24(2\\times LD-1.2)^{2}"},
            "es000562q1": {"id": "es000562q1", "latex": "A_{C}=A+(A_{F}\\times F_{EO})"},
        }
    )

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    result = _run(scenario())

    assert {eq.id: eq.latex for eq in result} == {
        "eg02500a": "Area=0.24(2\\times LD-1.2)^{2}",
        "es000562q1": "A_{C}=A+(A_{F}\\times F_{EO})",
    }


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_collapses_double_escaped_backslashes(mock_client_cls):
    # The site's own equation-map.json double-escapes some LaTeX commands
    # (two literal backslash characters instead of one), confirmed against
    # the same entry's plainText field, which shows the correctly rendered
    # symbol. A single backslash is what mathtext (and MathJax) expect.
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response(
        {"es000562q1": {"id": "es000562q1", "latex": "A_{C}=A+(A_{F}\\\\times F_{EO})"}}
    )

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    result = _run(scenario())

    assert result[0].latex == "A_{C}=A+(A_{F}\\times F_{EO})"


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_skips_entries_with_no_latex_field(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response(
        {
            "ex000108q1": {"id": "ex000108q1", "plainText": "S_s = smooth normalized SL + bZ"},
            "nbc.divBV2.part9.appendix.appnote134c.eq1": {
                "id": "nbc.divBV2.part9.appendix.appnote134c.eq1"
            },
            "eg02500a": {"id": "eg02500a", "latex": "Area=0.24(2\\times LD-1.2)^{2}"},
        }
    )

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    result = _run(scenario())

    assert [eq.id for eq in result] == ["eg02500a"]


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_returns_empty_list_for_empty_map(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response({})

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    assert _run(scenario()) == []


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_context_manager_opens_and_closes_one_shared_client(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response({})

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            await source.fetch_equations()
            await source.fetch_equations()

    _run(scenario())

    mock_client_cls.assert_called_once()
    mock_client.aclose.assert_awaited_once()
