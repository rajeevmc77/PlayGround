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


@pytest.mark.slow
def test_renders_a_real_mathml_equation_to_a_nontrivial_png(tmp_path):
    target = tmp_path / "eg02520a.png"

    with MathJaxRenderer() as renderer:
        renderer.render(_EG02520A_MATHML, target)

    assert target.exists()
    assert target.read_bytes().startswith(b"\x89PNG")
    # An empty/failed typeset would screenshot as a near-zero-size sliver; a
    # real "[f][a]N-hat" render at the default browser font size comes out
    # around 47x19px.
    from PIL import Image

    with Image.open(target) as img:
        assert img.width > 30
        assert img.height > 10
