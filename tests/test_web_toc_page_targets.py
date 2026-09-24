from web_toc.domain.models import WebNode
from web_toc.parsing.page_targets import page_targets, page_url


def _node(node_type, citation, path="", children=None):
    return WebNode(
        type=node_type,
        identifier="",
        citation=citation,
        title="",
        path=path,
        children=children or [],
    )


def _sample_tree():
    article = _node("article", "a.art1", "/code/a/1/1/1/1")
    subsection = _node("subsection", "a.sub1", "/code/a/1/1/1", [article])
    section = _node("section", "a.sect1", "/code/a/1/1", [subsection])
    appendix = _node("part_appendix", "a.app", "/code/a/1/appendix")
    part = _node("part", "a.part1", "/code/a/1", [section, appendix])
    preface = _node("article", "fm.preface", "/code/front-matter/preface")
    front = _node("division", "fm", "/code/front-matter", [preface])
    volume = _node("volume", "vol1", "/volume/1", [front, part])
    return _node("root", "root", "/", [volume])


def test_page_targets_includes_every_node_with_its_own_reading_page():
    citations = [node.citation for node in page_targets(_sample_tree())]
    assert citations == ["fm.preface", "a.part1", "a.sect1", "a.app"]


def test_page_targets_skips_volumes_and_divisions():
    # The live site has no reading page for either: /volume/N renders the
    # homepage and /code/<division> answers 403 - its own tree just expands.
    citations = {node.citation for node in page_targets(_sample_tree())}
    assert not citations & {"vol1", "fm"}


def test_page_targets_skips_subsections_and_regular_articles():
    # Their site pages are just a slice of the parent section page, so the
    # viewer derives them from it instead of scraping ~2500 near-duplicates.
    citations = {node.citation for node in page_targets(_sample_tree())}
    assert "a.sub1" not in citations
    assert "a.art1" not in citations


def test_page_targets_skips_root_and_nodes_without_a_path():
    tree = _node("root", "root", "/", [_node("section", "s.nopath", "")])
    assert page_targets(tree) == []


def test_page_targets_skips_body_nodes():
    sentence = _node("Sentence", "a.sect1.sent1")
    tree = _node("root", "root", "/", [_node("section", "a.sect1", "/code/a/1/1", [sentence])])
    assert [n.citation for n in page_targets(tree)] == ["a.sect1"]


def test_page_url_adds_version_and_effective_date():
    node = _node("section", "a.sect1", "/code/nbc.divA/1/1")
    url = page_url("https://site.example/", node, "2024", "2024-03-08")
    assert url == "https://site.example/code/nbc.divA/1/1?version=2024&date=2024-03-08"
