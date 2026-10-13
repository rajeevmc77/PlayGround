from mo_toc.parsing.vector_cluster import cluster_drawing_rects, exclude_overlapping_rects


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
