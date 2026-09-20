from web_toc.parsing.image_extractor import extract_images


def test_figure_matches_deepest_ancestor_citation():
    citations = {"nbc.divA.part1.sect1", "nbc.divA.part1.sect1.subsect1.art1"}
    content = {
        "id": "nbc.divA.part1.sect1",
        "subsections": [
            {
                "articles": [
                    {
                        "content": [
                            {
                                "type": "figure",
                                "id": "nbc.divA.part1.sect1.subsect1.art1.sent1.figure1",
                                "graphic": {"src": "bc-graphics/x1", "alt_text": "Diagram"},
                            }
                        ]
                    }
                ]
            }
        ],
    }
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert len(images) == 1
    assert images[0].owner_citation == "nbc.divA.part1.sect1.subsect1.art1"
    assert images[0].src == "bc-graphics/x1"
    assert images[0].alt_text == "Diagram"


def test_figure_falls_back_to_enclosing_node_when_no_deeper_match():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "id": "nbc.divA.part1.sect1",
        "subsections": [
            {
                "articles": [
                    {
                        "content": [
                            {
                                "type": "figure",
                                "id": "nbc.divA.part1.sect1.subsect9.art9.sent1.figure1",
                                "graphic": {
                                    "src": "bc-graphics/x2",
                                    "alt_text": "Untracked subsection",
                                },
                            }
                        ]
                    }
                ]
            }
        ],
    }
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert images[0].owner_citation == "nbc.divA.part1.sect1"


def test_figures_nested_inside_table_cells_are_found():
    citations = {"nbc.divBV2.part9.sect23.subsect13.art7"}
    content = {
        "id": "nbc.divBV2.part9.sect23",
        "subsections": [
            {
                "articles": [
                    {
                        "id": "nbc.divBV2.part9.sect23.subsect13.art7",
                        "content": [
                            {
                                "structure": {
                                    "body_rows": [
                                        {
                                            "cells": [
                                                {
                                                    "content": [
                                                        {
                                                            "type": "figure",
                                                            "id": (
                                                                "nbc.divBV2.part9.sect23."
                                                                "subsect13.art7.table1."
                                                                "row4.figure23"
                                                            ),
                                                            "graphic": {
                                                                "src": "bc-graphics/gg00556a",
                                                                "alt_text": (
                                                                    "Three storey building "
                                                                    "configuration"
                                                                ),
                                                            },
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        ],
                    }
                ]
            }
        ],
    }
    images = extract_images(content, citations, fallback_citation="nbc.divBV2.part9.sect23")
    assert len(images) == 1
    assert images[0].owner_citation == "nbc.divBV2.part9.sect23.subsect13.art7"


def test_multiple_figures_in_one_content_json_are_all_extracted():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            {
                "type": "figure",
                "id": "nbc.divA.part1.sect1.figA",
                "graphic": {"src": "a", "alt_text": "A"},
            },
            {
                "type": "figure",
                "id": "nbc.divA.part1.sect1.figB",
                "graphic": {"src": "b", "alt_text": "B"},
            },
        ]
    }
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert {img.src for img in images} == {"a", "b"}


def test_no_figures_returns_empty_list():
    content = {"id": "nbc.divA.part1.sect1", "subsections": []}
    assert extract_images(content, {"nbc.divA.part1.sect1"}, "nbc.divA.part1.sect1") == []


def test_figure_falls_back_when_id_shares_no_prefix_with_any_citation():
    citations = {"nbc.divZ.part9.sect1"}
    content = {
        "content": [
            {
                "type": "figure",
                "id": "other.namespace.figure1",
                "graphic": {"src": "x", "alt_text": "X"},
            }
        ]
    }
    images = extract_images(content, citations, fallback_citation="nbc.divZ.part9.sect1")
    assert len(images) == 1
    assert images[0].owner_citation == "nbc.divZ.part9.sect1"


def test_figure_without_id_is_skipped_not_crashed():
    citations = {"nbc.divA.part1.sect1"}
    content = {
        "content": [
            {
                "type": "figure",
                "graphic": {"src": "malformed", "alt_text": "No id"},
            },
            {
                "type": "figure",
                "id": "nbc.divA.part1.sect1.figGood",
                "graphic": {"src": "good", "alt_text": "Good"},
            },
        ]
    }
    images = extract_images(content, citations, fallback_citation="nbc.divA.part1.sect1")
    assert len(images) == 1
    assert images[0].src == "good"
    assert images[0].owner_citation == "nbc.divA.part1.sect1"
