import pytest

from web_toc.parsing.content_url import content_url
from web_toc.parsing.site_source import HttpxWebSource
from web_toc.parsing.tree_builder import build_tree

BASE_URL = "https://dev.buildingcode.gov.bc.ca"
VERSION = "2024"


def _find(node, citation):
    if node.citation == citation:
        return node
    for child in node.children:
        found = _find(child, citation)
        if found is not None:
            return found
    return None


@pytest.mark.slow
def test_navigation_tree_has_two_volumes():
    source = HttpxWebSource(BASE_URL, VERSION)
    root = build_tree(source.fetch_navigation_tree())
    assert len(root.children) == 2


@pytest.mark.slow
def test_front_matter_preface_content_is_fetchable():
    source = HttpxWebSource(BASE_URL, VERSION)
    root = build_tree(source.fetch_navigation_tree())
    preface = _find(root, "nbc.2020.preface")
    assert preface is not None

    url = content_url(preface, VERSION)
    content = source.fetch_content(url)

    assert content is not None
    assert content["id"] == "nbc.2020.preface"
