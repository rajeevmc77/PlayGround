from mo_toc.parsing.vector_cluster import (
    cluster_drawing_rects,
    exclude_overlapping_rects,
    merge_equation_fragments,
)


def test_empty_input_returns_empty_list():
    assert cluster_drawing_rects([]) == []


def test_single_substantial_rect_becomes_its_own_cluster():
    assert cluster_drawing_rects([(0, 0, 50, 50)]) == [(0, 0, 50, 50)]


def test_thin_rule_line_is_filtered_out():
    assert cluster_drawing_rects([(0, 0, 200, 0.5)]) == []


def test_small_decorative_mark_is_filtered_out():
    assert cluster_drawing_rects([(0, 0, 3, 3)]) == []


def test_adjacent_rects_merge_into_one_cluster():
    result = cluster_drawing_rects([(0, 0, 30, 30), (32, 0, 60, 30)])
    assert result == [(0, 0, 60, 30)]


def test_distant_rects_stay_separate_clusters():
    result = cluster_drawing_rects([(0, 0, 30, 30), (200, 200, 230, 230)])
    assert len(result) == 2


def test_many_small_segments_merge_into_one_substantial_cluster():
    # simulates a curve built from tiny bezier-segment bounding boxes
    segments = [(i, 0, i + 3, 3) for i in range(0, 400, 3)]
    result = cluster_drawing_rects(segments)
    assert len(result) == 1
    assert result[0][2] - result[0][0] > 390


def test_exclude_overlapping_rects_drops_clusters_over_raster_images():
    clusters = [(0, 0, 30, 30), (200, 200, 230, 230)]
    existing = [(5, 5, 25, 25)]
    assert exclude_overlapping_rects(clusters, existing) == [(200, 200, 230, 230)]


def test_exclude_overlapping_rects_keeps_all_when_no_raster_images():
    clusters = [(0, 0, 30, 30)]
    assert exclude_overlapping_rects(clusters, []) == clusters


def test_stacked_fraction_pieces_merge_when_gap_exceeds_general_margin():
    numerator = (0, 0, 60, 8)
    denominator = (0, 20, 60, 28)  # 12pt gap: > MERGE_MARGIN(5), within STACK_GAP_LIMIT
    result = merge_equation_fragments([numerator, denominator])
    assert result == [(0, 0, 60, 28)]


def test_two_separate_diagrams_stay_separate():
    top = (0, 0, 50, 50)
    bottom = (0, 60, 50, 110)  # 10pt gap, but the union is too tall to be an equation
    result = merge_equation_fragments([top, bottom])
    assert sorted(result) == sorted([top, bottom])


def test_stacked_but_not_horizontally_overlapping_stays_separate():
    left = (0, 0, 40, 8)
    right = (100, 20, 140, 28)
    result = merge_equation_fragments([left, right])
    assert sorted(result) == sorted([left, right])


def test_gap_beyond_the_tallest_known_equation_stays_separate():
    top = (0, 0, 60, 8)
    bottom = (0, 100, 60, 108)  # 92pt gap, well past STACK_GAP_LIMIT
    result = merge_equation_fragments([top, bottom])
    assert sorted(result) == sorted([top, bottom])


def test_a_thin_bar_between_numerator_and_denominator_is_absorbed_into_one_equation():
    numerator = (0, 0, 60, 8)
    bar = (0, 14, 60, 14.5)
    denominator = (0, 20, 60, 28)
    result = merge_equation_fragments([numerator, bar, denominator])
    assert result == [(0, 0, 60, 28)]


def test_a_tall_diagram_near_a_formula_stays_separate():
    formula = (0, 0, 60, 8)
    diagram = (0, 20, 60, 120)  # 12pt gap, full x overlap, but the union is 120pt tall
    result = merge_equation_fragments([formula, diagram])
    assert sorted(result) == sorted([formula, diagram])


def test_empty_and_single_cluster_are_unchanged():
    assert merge_equation_fragments([]) == []
    assert merge_equation_fragments([(0, 0, 60, 8)]) == [(0, 0, 60, 8)]
