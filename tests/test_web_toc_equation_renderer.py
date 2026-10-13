"""Real MathJax rendering in a headless browser - no network beyond the
MathJax CDN bundle every page in this pipeline already loads. Every test here
launches Chromium and fetches that bundle from cdnjs, so the whole module is
`slow`; test_web_toc_equation_renderer_wiring.py covers the render wiring in
the default suite with Playwright faked out."""

import asyncio
import time

import pytest

from web_toc.domain.models import EquationSource
from web_toc.parsing.equation_renderer import EquationRenderer

pytestmark = pytest.mark.slow


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


def test_raises_value_error_when_latex_has_a_tex_error(tmp_path):
    # MathJax renders a TeX error in place and still produces a container, so
    # without an explicit check a junk "\undefinedcmd x" image would be saved.
    target = tmp_path / "eq.png"
    with pytest.raises(ValueError):
        _render(EquationSource(latex=r"\undefinedcmd x"), target)
    assert not target.exists()


def test_unrenderable_equation_fails_fast_not_on_the_screenshot_timeout(tmp_path):
    # Times the render alone (not the browser launch or MathJax download):
    # the old path waited out the 10 s screenshot timeout before raising.
    elapsed = []

    async def go():
        async with EquationRenderer() as renderer:
            started = time.monotonic()
            with pytest.raises(ValueError):
                bad = EquationSource(latex="", mathml="<not-math>not real markup<")
                await renderer.render(bad, tmp_path / "eq.png")
            elapsed.append(time.monotonic() - started)

    asyncio.run(go())
    assert elapsed[0] < 5


def test_renders_after_a_previous_render_raised_on_the_same_instance(tmp_path):
    async def go():
        async with EquationRenderer() as renderer:
            with pytest.raises(ValueError):
                bad = EquationSource(latex=r"\undefinedcmd x")
                await renderer.render(bad, tmp_path / "bad.png")
            await renderer.render(EquationSource(latex="x^2"), tmp_path / "good.png")

    asyncio.run(go())
    assert (tmp_path / "good.png").read_bytes().startswith(b"\x89PNG")


def test_raises_value_error_for_malformed_latex_with_unbalanced_braces(tmp_path):
    with pytest.raises(ValueError):
        _render(EquationSource(latex=r"\frac{1}{2"), tmp_path / "eq.png")


def _ink_on_edges(path) -> dict[str, bool]:
    from PIL import Image

    with Image.open(path) as img:
        grey = img.convert("L")
        width, height = grey.size
        edges = {
            "top": [(x, 0) for x in range(width)],
            "bottom": [(x, height - 1) for x in range(width)],
            "left": [(0, y) for y in range(height)],
            "right": [(width - 1, y) for y in range(height)],
        }
        return {side: any(grey.getpixel(p) < 128 for p in px) for side, px in edges.items()}


# An inline fraction (es013709q3, eg02664a, eg02643a on the site) stands
# taller than its inline mjx-container's own box: a screenshot of just that
# box cut the numerator's top and the denominator's bottom off.
_INLINE_FRACTION_MATHML = """<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">
   <mi>A</mi><mo>=</mo>
   <mfrac>
      <mrow><mn>1</mn><mn>000</mn><mi>A</mi></mrow>
      <mrow><mi>max</mi><mo>(</mo><msup><mi>L</mi><mn>2</mn></msup><mo>,</mo><mn>25</mn><mo>)</mo></mrow>
   </mfrac>
</math>"""
_DISPLAY_FRACTION_MATHML = "<math display='block'><mfrac><mi>a</mi><mi>b</mi></mfrac></math>"


@pytest.mark.parametrize(
    "source",
    [
        EquationSource(latex="", mathml=_INLINE_FRACTION_MATHML),
        EquationSource(latex=r"\frac{w^{2}_{s}}{l_{s}}"),
        EquationSource(latex="x", mathml=_DISPLAY_FRACTION_MATHML),
    ],
    ids=["inline-mathml-fraction", "latex-fraction", "display-mathml-fraction"],
)
def test_the_png_holds_the_whole_formula_not_clipped_at_any_edge(tmp_path, source):
    target = tmp_path / "eq.png"
    _render(source, target)
    assert _ink_on_edges(target) == {"top": False, "bottom": False, "left": False, "right": False}


# Real mathml for eg02520a from the live equation-map.json: the site flattens
# its latex field into raw newlines and a bare combining-macron character, so
# its latex is unusable, but this mathml is what the site's own MathJax
# actually renders, confirmed by inspecting the live page's DOM.
_EG02520A_MATHML = """<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">
   <mtext xmlns="">[f]</mtext>
   <mtext xmlns="">[a]</mtext>
   <mover xmlns="">
      <mrow>
         <mi>N</mi>
      </mrow>
      <mo>^</mo>
   </mover>
   <mover xmlns="">
      <mrow>
         <mtext>̄</mtext>
      </mrow>
      <mo>^</mo>
   </mover>
</math>"""


def test_renders_a_real_mathml_equation_to_a_nontrivial_png(tmp_path):
    from PIL import Image

    target = tmp_path / "eg02520a.png"
    _render(EquationSource(latex="", mathml=_EG02520A_MATHML), target)

    # An empty/failed typeset would screenshot as a near-zero-size sliver; a
    # real "[f][a]N-hat" render at the default browser font size comes out
    # around 47x19px.
    assert target.read_bytes().startswith(b"\x89PNG")
    with Image.open(target) as img:
        assert img.width > 30
        assert img.height > 10
