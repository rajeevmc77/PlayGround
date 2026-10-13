"""Real MathJax rendering in a headless browser - no network beyond the
MathJax CDN bundle every page in this pipeline already loads."""

import asyncio

import pytest

from web_toc.domain.models import EquationSource
from web_toc.parsing.equation_renderer import EquationRenderer


def _render(source: EquationSource, path):
    async def go():
        async with EquationRenderer() as renderer:
            await renderer.render(source, path)

    asyncio.run(go())


def test_renders_mathml_to_a_png(tmp_path):
    target = tmp_path / "eq.png"
    _render(EquationSource(latex="x", mathml="<math><mi>x</mi></math>"), target)
    assert target.read_bytes().startswith(b"\x89PNG")


def test_falls_back_to_latex_when_mathml_is_missing(tmp_path):
    target = tmp_path / "eq.png"
    _render(EquationSource(latex="x^2"), target)
    assert target.read_bytes().startswith(b"\x89PNG")


def test_normalizes_the_sites_double_escaped_backslashes_in_latex_fallback(tmp_path):
    # The site's own latex export double-escapes commands like \\times - a
    # correctly-normalized double-escaped string must render identically to
    # the already-correct single-backslash form, not merely "without
    # crashing" (MathJax tolerates plenty of malformed input silently).
    normalized = tmp_path / "normalized.png"
    doubled = tmp_path / "doubled.png"
    _render(EquationSource(latex="a\\times b"), normalized)
    _render(EquationSource(latex="a\\\\times b"), doubled)
    assert doubled.read_bytes() == normalized.read_bytes()


def test_renders_a_less_than_sign_in_latex_instead_of_raising(tmp_path):
    target = tmp_path / "eq.png"
    _render(EquationSource(latex="a<b"), target)
    assert target.read_bytes().startswith(b"\x89PNG")


def test_raises_value_error_when_mathjax_cannot_typeset(tmp_path):
    target = tmp_path / "eq.png"
    with pytest.raises(ValueError):
        _render(EquationSource(latex="", mathml="<not-math>not real markup<"), target)


def test_renders_several_equations_in_sequence_on_one_shared_instance(tmp_path):
    async def go():
        async with EquationRenderer() as renderer:
            await renderer.render(
                EquationSource(latex="x", mathml="<math><mi>x</mi></math>"), tmp_path / "a.png"
            )
            await renderer.render(
                EquationSource(latex="y", mathml="<math><mi>y</mi></math>"), tmp_path / "b.png"
            )

    asyncio.run(go())
    assert (tmp_path / "a.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "b.png").read_bytes().startswith(b"\x89PNG")
