from mo_toc.domain.image_classification import is_decorative, is_equation_shaped


def test_small_square_icon_is_decorative():
    assert is_decorative(20, 22) is True


def test_wide_short_single_line_formula_is_not_decorative():
    # Article 4.1.6.5.(3)'s real F=... formula on the source PDF: 259x34pt -
    # far too wide/short a shape for a logo or icon, but under the old
    # "smaller dimension < 40pt" rule it was wrongly hidden as decorative.
    assert is_decorative(259.2, 33.8) is False


def test_tall_narrow_shape_is_not_decorative():
    assert is_decorative(15, 90) is False


def test_large_square_diagram_is_not_decorative():
    assert is_decorative(200, 200) is False


def test_boundary_area_exactly_at_threshold_is_not_decorative():
    assert is_decorative(40, 40) is False


def test_boundary_aspect_ratio_exactly_at_threshold_is_decorative():
    assert is_decorative(20, 40) is True


def test_zero_dimension_is_not_decorative():
    assert is_decorative(0, 10) is False
    assert is_decorative(10, 0) is False


def test_negative_dimension_is_not_decorative():
    assert is_decorative(-5, 10) is False


def test_wide_short_single_line_formula_is_equation_shaped():
    # Same real formula crop as above (259.2x33.8pt) - wide/short is exactly
    # the shape an inline equation renders as, never a genuine diagram.
    assert is_equation_shaped(259.2, 33.8) is True


def test_square_diagram_is_not_equation_shaped():
    assert is_equation_shaped(200, 200) is False


def test_tall_narrow_shape_is_not_equation_shaped():
    # A formula reads left-to-right on one text line - never portrait.
    assert is_equation_shaped(15, 90) is False


def test_boundary_aspect_ratio_exactly_at_threshold_is_equation_shaped():
    assert is_equation_shaped(40, 20) is True


def test_just_under_aspect_ratio_threshold_is_not_equation_shaped():
    assert is_equation_shaped(39, 20) is False


def test_zero_dimension_is_not_equation_shaped():
    assert is_equation_shaped(0, 10) is False
    assert is_equation_shaped(10, 0) is False


def test_negative_dimension_is_not_equation_shaped():
    assert is_equation_shaped(-5, 10) is False
