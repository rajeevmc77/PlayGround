from web_toc.domain.models import WebImage, WebNode


def test_web_node_defaults_to_no_children():
    node = WebNode(
        type="section",
        identifier="1.1",
        citation="nbc.divA.part1.sect1",
        title="General",
        path="/code/nbc.divA/1/1",
    )
    assert node.children == []


def test_web_node_children_are_independent_between_instances():
    a = WebNode(
        type="part", identifier="1", citation="nbc.divA.part1", title="", path="/code/nbc.divA/1"
    )
    b = WebNode(
        type="part", identifier="2", citation="nbc.divA.part2", title="", path="/code/nbc.divA/2"
    )
    a.children.append("x")
    assert b.children == []


def test_web_node_unified_number_defaults_to_empty_string():
    node = WebNode(
        type="section",
        identifier="1.1",
        citation="nbc.divA.part1.sect1",
        title="General",
        path="/code/nbc.divA/1/1",
    )
    assert node.unified_number == ""


def test_web_node_unified_number_can_be_set():
    node = WebNode(
        type="part",
        identifier="1",
        citation="nbc.divA.part1",
        title="",
        path="/code/nbc.divA/1",
        unified_number="1.1",
    )
    assert node.unified_number == "1.1"


def test_web_node_holds_nested_children():
    child = WebNode(
        type="article",
        identifier="1.1.1.1",
        citation="nbc.divA.part1.sect1.subsect1.art1",
        title="Application",
        path="/code/nbc.divA/1/1/1/1",
    )
    parent = WebNode(
        type="subsection",
        identifier="1.1.1",
        citation="nbc.divA.part1.sect1.subsect1",
        title="Application",
        path="/code/nbc.divA/1/1/1",
        children=[child],
    )
    assert parent.children[0].citation == "nbc.divA.part1.sect1.subsect1.art1"


def test_web_image_holds_graphic_and_owner_fields():
    img = WebImage(
        id="nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23",
        src="bc-graphics/gg00556a",
        alt_text="Three storey building configuration",
        owner_citation="nbc.divBV2.part9.sect23.subsect13.art7",
    )
    assert img.src == "bc-graphics/gg00556a"
    assert img.owner_citation == "nbc.divBV2.part9.sect23.subsect13.art7"


def test_web_image_local_path_defaults_to_empty_string():
    img = WebImage(
        id="nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23",
        src="bc-graphics/gg00556a",
        alt_text="Three storey building configuration",
        owner_citation="nbc.divBV2.part9.sect23.subsect13.art7",
    )
    assert img.local_path == ""


def test_web_image_local_path_can_be_set():
    img = WebImage(
        id="nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23",
        src="bc-graphics/gg00556a",
        alt_text="Three storey building configuration",
        owner_citation="nbc.divBV2.part9.sect23.subsect13.art7",
        local_path="web_images/nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23.jpg",
    )
    assert (
        img.local_path
        == "web_images/nbc.divBV2.part9.sect23.subsect13.art7.table1.row4.figure23.jpg"
    )
