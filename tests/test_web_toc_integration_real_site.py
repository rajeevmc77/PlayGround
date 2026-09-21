import asyncio

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
    async def scenario():
        async with HttpxWebSource(BASE_URL, VERSION) as source:
            return build_tree(await source.fetch_navigation_tree())

    root = asyncio.run(scenario())
    assert len(root.children) == 2


@pytest.mark.slow
def test_front_matter_preface_content_is_fetchable():
    async def scenario():
        async with HttpxWebSource(BASE_URL, VERSION) as source:
            root = build_tree(await source.fetch_navigation_tree())
            preface = _find(root, "nbc.2020.preface")
            assert preface is not None

            url = content_url(preface, VERSION)
            return await source.fetch_content(url)

    content = asyncio.run(scenario())
    assert content is not None
    assert content["id"] == "nbc.2020.preface"
