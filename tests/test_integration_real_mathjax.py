import pytest

from equation_export.rendering.mathjax_renderer import MathJaxRenderer

# Real mathml for eg02520a from the live equation-map.json: the site flattens
# its latex field into raw newlines and a bare combining-macron character
# (see equation_needs_mathml_fallback), but this mathml is what the site's
# own MathJax actually renders, confirmed by inspecting the live page's DOM.
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

# Real mathml for eg02626a (the "RSI parallel" fraction-of-a-fraction
# equation) - a second, structurally different equation from the live
# equation-map.json, used to catch a regression of the bug where reloading
# the whole page per equation only auto-typeset the first one and left every
# later equation timing out.
_EG02626A_MATHML = """<math display="block">
   <mi>RSI</mi>
   <msub><mrow/><mrow><mi>parallel</mi></mrow></msub>
   <mo>=</mo>
   <mfrac>
      <mrow><mn>100</mn></mrow>
      <mrow>
         <mfrac>
            <mrow><mtext>%</mtext><mi>area</mi><mi>of</mi><mi>framing</mi></mrow>
            <mrow><mi>RSI</mi><msub><mrow/><mrow><mi>F</mi></mrow></msub></mrow>
         </mfrac>
         <mo>+</mo>
         <mfrac>
            <mrow><mtext>%</mtext><mi>area</mi><mi>of</mi><mi>cavity</mi></mrow>
            <mrow><mi>RSI</mi><msub><mrow/><mrow><mi>C</mi></mrow></msub></mrow>
         </mfrac>
      </mrow>
   </mfrac>
</math>"""


def _assert_nontrivial_png(target):
    assert target.exists()
    assert target.read_bytes().startswith(b"\x89PNG")
    from PIL import Image

    with Image.open(target) as img:
        assert img.width > 30
        assert img.height > 10


@pytest.mark.slow
def test_renders_a_real_mathml_equation_to_a_nontrivial_png(tmp_path):
    target = tmp_path / "eg02520a.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_EG02520A_MATHML, target)

    # An empty/failed typeset would screenshot as a near-zero-size sliver; a
    # real "[f][a]N-hat" render at the default browser font size comes out
    # around 47x19px.
    _assert_nontrivial_png(target)


@pytest.mark.slow
def test_renders_multiple_equations_in_sequence_on_the_same_renderer(tmp_path):
    # Regression test: an earlier version reloaded the whole page (and its
    # MathJax script) per render() call, which only auto-typeset the first
    # equation - every later one silently timed out waiting for a container
    # that MathJax's auto-render never re-triggered for.
    first = tmp_path / "eg02520a.png"
    second = tmp_path / "eg02626a.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_EG02520A_MATHML, first)
        renderer.render(_EG02626A_MATHML, second)

    _assert_nontrivial_png(first)
    _assert_nontrivial_png(second)
