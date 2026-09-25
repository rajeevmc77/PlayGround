from web_toc.domain.models import WebNode
from web_toc.parsing.content_url import content_url


def _node(node_type, citation, path=""):
    return WebNode(type=node_type, identifier="", citation=citation, title="", path=path)


def test_section_node_returns_section_url():
    node = _node("section", "nbc.divA.part1.sect1")
    assert content_url(node, "2024") == "/data/2024/content/nbc-diva/part-1/section-1.json"


def test_section_node_under_second_volume_division_slug():
    node = _node("section", "nbc.divBV2.part9.sect23")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divbv2/part-9/section-23.json"


def test_part_appendix_node_returns_appendix_url():
    node = _node("part_appendix", "nbc.divBV2.part9.appendix")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divbv2/part-9/appendix.json"


def test_part_appendix_with_section_segment_maps_to_part_appendix_url():
    # Part 10's nav citation carries a section segment the content URL does not
    # (verified against the live site: part-10/appendix.json is the JSON one).
    node = _node("part_appendix", "nbc.divB.part10.sect4.appendix")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divb/part-10/appendix.json"


def test_division_appendix_node_lowercases_letter():
    node = _node("division_appendix", "nbc.divB.appendixC")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divb/appendix-c.json"


def test_spectables_node_returns_spectables_url():
    node = _node("spectables", "nbc.divBV2.part9.spectables1")
    assert content_url(node, "2024") == "/data/2024/content/nbc-divbv2/part-9/spectables/1.json"


def test_front_matter_article_uses_last_path_segment():
    node = _node("article", "nbc.2020.preface", path="/code/front-matter/preface")
    assert content_url(node, "2024") == "/data/2024/content/front-matter/preface.json"


def test_regular_article_returns_none():
    # A non-front-matter article's figures are covered by its parent section's
    # own content fetch - it never gets its own content URL.
    node = _node("article", "nbc.divA.part1.sect1.subsect1.art1", path="/code/nbc.divA/1/1/1/1")
    assert content_url(node, "2024") is None


def test_index_and_conversions_return_none():
    assert content_url(_node("index", "nbc.2020.vol2.index"), "2024") is None
    assert content_url(_node("conversions", "nbc.2020.vol2.conversions"), "2024") is None


def test_structural_types_return_none():
    for node_type in ("volume", "division", "part", "subsection"):
        assert content_url(_node(node_type, "nbc.divA"), "2024") is None


def test_version_is_used_in_url():
    node = _node("section", "nbc.divA.part1.sect1")
    assert content_url(node, "2020") == "/data/2020/content/nbc-diva/part-1/section-1.json"
