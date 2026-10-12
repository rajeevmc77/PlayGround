import pytest

from llm_compare.domain.anchors import nearest_anchor

IDS = {
    "nbc.divA.part1.sect1",
    "nbc.divA.part1.sect1.art1.table1",
    "nbc.divA.part1.sect1.art1.table1.row2",
    "plain",
}


def test_an_id_the_page_has_is_the_exact_anchor():
    assert nearest_anchor("nbc.divA.part1.sect1.art1.table1.row2", IDS) == (
        "nbc.divA.part1.sect1.art1.table1.row2",
        True,
    )


def test_one_level_up_is_the_nearest_enclosing_anchor():
    assert nearest_anchor("nbc.divA.part1.sect1.art1.table1.row2.cell3", IDS) == (
        "nbc.divA.part1.sect1.art1.table1.row2",
        False,
    )


def test_two_levels_up_is_found_too():
    found = nearest_anchor("nbc.divA.part1.sect1.art1.table1.row9.cell3", IDS)
    assert found == ("nbc.divA.part1.sect1.art1.table1", False)


def test_the_longest_prefix_wins_over_a_shorter_one():
    assert nearest_anchor("nbc.divA.part1.sect1.art1.table1.row2.x.y.z", IDS) == (
        "nbc.divA.part1.sect1.art1.table1.row2",
        False,
    )


def test_no_prefix_on_the_page_gives_none():
    assert nearest_anchor("other.part9.fig1", IDS) is None


def test_an_id_without_dots_is_exact_or_nothing():
    assert nearest_anchor("plain", IDS) == ("plain", True)
    assert nearest_anchor("absent", IDS) is None


@pytest.mark.parametrize("element_id", ["", "."])
def test_an_empty_id_has_no_anchor(element_id):
    assert nearest_anchor(element_id, IDS) is None


def test_an_empty_page_has_no_anchor():
    assert nearest_anchor("nbc.divA", set()) is None
