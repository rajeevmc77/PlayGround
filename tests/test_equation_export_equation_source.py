import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from equation_export.parsing.equation_source import HttpxEquationSource, _normalize_latex


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


def test_normalize_latex_inserts_space_after_times_glued_to_a_letter():
    assert _normalize_latex("Area=0.24(2\\timesLD-1.2)^{2}") == "Area=0.24(2\\times LD-1.2)^{2}"


def test_normalize_latex_inserts_space_after_leq_glued_to_a_letter():
    assert _normalize_latex("C\\leqC_{max}") == "C\\leq C_{max}"


def test_normalize_latex_inserts_space_after_sum_glued_to_a_letter():
    assert _normalize_latex("\\sumh_{i}w_{i}") == "\\sum h_{i}w_{i}"


def test_normalize_latex_fixes_every_occurrence_in_the_same_string():
    assert (
        _normalize_latex("SensibleHeat=0.00123\\timesQ\\times(T_{e}-T_{o})")
        == "SensibleHeat=0.00123\\times Q\\times(T_{e}-T_{o})"
    )


def test_normalize_latex_leaves_already_spaced_commands_untouched():
    assert _normalize_latex("A_{C}=A+(A_{F}\\times F_{EO})") == "A_{C}=A+(A_{F}\\times F_{EO})"


def test_normalize_latex_leaves_commands_followed_by_non_letters_untouched():
    assert _normalize_latex("\\sum_{i}h_{i}") == "\\sum_{i}h_{i}"
    assert _normalize_latex("a\\times(b)") == "a\\times(b)"
    assert _normalize_latex("a\\times2") == "a\\times2"


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_fixes_glued_commands_in_the_fetched_latex(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response(
        {"eg02500a": {"id": "eg02500a", "latex": "Area=0.24(2\\timesLD-1.2)^{2}"}}
    )

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    result = _run(scenario())

    assert result[0].latex == "Area=0.24(2\\times LD-1.2)^{2}"


def test_normalize_latex_replaces_text_command_with_mathrm():
    # matplotlib's mathtext has no \text command and prints it literally
    # (visible backslash and braces) instead of raising - \mathrm is the
    # closest supported equivalent (upright, non-italic) for these short
    # annotations like [f], [a], units, or punctuation.
    assert _normalize_latex("\\text{[f]}\\text{[a]}N") == "\\mathrm{[f]}\\mathrm{[a]}N"


def test_normalize_latex_escapes_a_bare_percent_sign():
    # matplotlib's mathtext treats an unescaped % as a comment start, same as
    # real TeX, silently truncating everything after it.
    assert _normalize_latex("\\text{%}") == "\\mathrm{\\%}"


def test_normalize_latex_leaves_an_already_escaped_percent_untouched():
    assert _normalize_latex("a\\%b") == "a\\%b"


def test_normalize_latex_replaces_private_use_parenthesis_glyphs():
    # Confirmed by comparing eg02650a (uses these glyphs) against eg02652a,
    # the identical equation spelled with real parentheses in the site's own
    # data: / stand in for "(" and ")" and have no glyph in any
    # real font, so matplotlib would otherwise draw a missing-glyph box.
    assert _normalize_latex("C_{a}x") == "C_{a}(x)"


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_captures_the_mathml_field(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response(
        {
            "eg02500a": {
                "id": "eg02500a",
                "latex": "Area=0.24(2\\times LD-1.2)^{2}",
                "mathml": "<math><mi>Area</mi></math>",
            }
        }
    )

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    result = _run(scenario())

    assert result[0].mathml == "<math><mi>Area</mi></math>"


@patch("equation_export.parsing.equation_source.httpx.AsyncClient")
def test_fetch_equations_defaults_mathml_to_none_when_absent(mock_client_cls):
    mock_client = _mock_client(mock_client_cls)
    mock_client.get.return_value = _fake_response(
        {"eg02500a": {"id": "eg02500a", "latex": "Area=0.24(2\\times LD-1.2)^{2}"}}
    )

    async def scenario():
        async with HttpxEquationSource("https://dev.buildingcode.gov.bc.ca", "2024") as source:
            return await source.fetch_equations()

    result = _run(scenario())

    assert result[0].mathml is None


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
