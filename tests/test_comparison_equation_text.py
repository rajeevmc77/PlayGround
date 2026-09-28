"""The text side of an equation comparison: the PDF's formula image read by
OCR against the site's own formula text (its MathJax alt text). A pixel
comparison can't match the PDF's typewriter-set formulas to the site's
MathJax renders; the text often can, where OCR reads the formula well."""

from comparison.equation_text import formula_text_matches, shows_mathjax_error


def test_a_well_read_formula_matches_the_sites_formula_text():
    # 3.2.3.1.Eq1, as Tesseract reads the PDF's formula image.
    assert formula_text_matches("Area = 0.24(2 x LD—- 1.2)", "Area=0.24(2×LD-1.2)^2")


def test_a_garbled_reading_does_not_match():
    # A-9.36.2.4.(1).Eq4: its stacked fraction reads as noise.
    assert not formula_text_matches(
        "100\nRSlt1 = em —ssaay = 8-28(m? x K)/W",
        "RSI_T1=(100)/(((0.77)/(1.81))+((99.23)/(5.33)))=5.25(m^2×K)/W",
    )


def test_another_formula_does_not_match():
    assert not formula_text_matches("Area = 0.24(2 x LD—- 1.2)", "A_C=A+(A_F×F_EO)")


def test_nothing_read_matches_nothing():
    assert not formula_text_matches("", "Area=0.24(2×LD-1.2)^2")
    assert not formula_text_matches("   ", "")


def test_the_sites_mathjax_error_marker_is_recognised():
    # The site renders commands MathJax doesn't know as "[f]", "[a]" - shown
    # to readers in front of the formula, which the PDF doesn't have.
    assert shows_mathjax_error("[f]l_cs=2w_s-(w^2_s)/(l_s)")
    assert shows_mathjax_error("[f][a] N ^ ̄ ^")
    assert not shows_mathjax_error("C_a=(1)/(C_b)for0<x≤b/4")
    assert not shows_mathjax_error("")
