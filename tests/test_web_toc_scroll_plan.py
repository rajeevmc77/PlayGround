from web_toc.parsing.scroll_plan import short_tables


def test_short_tables_lists_tables_rendered_below_their_expected_rows():
    rendered = {"t1": 121, "t2": 5}
    expected = {"t1": 5949, "t2": 5}

    assert short_tables(rendered, expected) == {"t1": [121, 5949]}


def test_short_tables_counts_a_table_missing_from_the_page_as_zero_rows():
    assert short_tables({}, {"t1": 3}) == {"t1": [0, 3]}


def test_short_tables_is_empty_when_every_table_is_complete():
    assert short_tables({"t1": 3}, {"t1": 3}) == {}


def test_short_tables_ignores_extra_rendered_rows_and_unexpected_tables():
    assert short_tables({"t1": 4, "other": 9}, {"t1": 3}) == {}


def test_short_tables_with_nothing_expected_is_empty():
    assert short_tables({"t1": 2}, {}) == {}
