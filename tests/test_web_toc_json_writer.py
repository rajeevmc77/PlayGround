import json

from web_toc.domain.models import WebImage, WebNode
from web_toc.output.json_writer import write_json


def test_write_json_roundtrips_tree_and_images(tmp_path):
    child = WebNode(
        type="section",
        identifier="1.1",
        citation="nbc.divA.part1.sect1",
        title="General",
        path="/code/nbc.divA/1/1",
    )
    root = WebNode(
        type="root",
        identifier="",
        citation="root",
        title="BC Building Code",
        path="/",
        children=[child],
    )
    image = WebImage(
        id="nbc.divA.part1.sect1.fig1",
        src="bc-graphics/x",
        alt_text="Diagram",
        owner_citation="nbc.divA.part1.sect1",
    )

    out_path = tmp_path / "web_toc.json"
    write_json(root, [image], str(out_path))

    payload = json.loads(out_path.read_text())
    assert payload["tree"]["type"] == "root"
    assert payload["tree"]["children"][0]["citation"] == "nbc.divA.part1.sect1"
    assert payload["images"][0]["src"] == "bc-graphics/x"


def test_write_json_drops_empty_heading_keys_recursively(tmp_path):
    grandchild = WebNode(type="Sentence", identifier="(1)", citation="s", title="", path="")
    child = WebNode(
        type="part",
        identifier="1",
        citation="p",
        title="Part 1 - Compliance",
        path="",
        heading="Part 1",
        children=[grandchild],
    )
    root = WebNode(
        type="root", identifier="", citation="root", title="", path="/", children=[child]
    )

    out_path = tmp_path / "web.json"
    write_json(root, [], str(out_path))

    tree = json.loads(out_path.read_text())["tree"]
    part = tree["children"][0]
    assert "heading" not in tree
    assert part["heading"] == "Part 1"
    assert "heading" not in part["children"][0]
    assert part["children"][0]["title"] == ""  # every other field is kept as is


def test_write_json_creates_parent_directories(tmp_path):
    root = WebNode(type="root", identifier="", citation="root", title="", path="/")
    out_path = tmp_path / "nested" / "web_toc.json"
    write_json(root, [], str(out_path))
    assert out_path.exists()


_LOCATION = {
    "page_file": "web_pages/p.html",
    "xpath": "/html/body/main/div/main/div[1]",
    "bbox": {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0},
}


def test_write_json_drops_unset_locations_and_keeps_set_ones(tmp_path):
    located = WebNode(
        type="Sentence", identifier="(1)", citation="s", title="", path="", location=_LOCATION
    )
    unlocated = WebNode(type="Sentence", identifier="(2)", citation="s2", title="", path="")
    root = WebNode(
        type="root",
        identifier="",
        citation="root",
        title="",
        path="/",
        children=[located, unlocated],
    )
    images = [
        WebImage(id="a", src="x", alt_text="", owner_citation="s", location=_LOCATION),
        WebImage(id="b", src="y", alt_text="", owner_citation="s"),
    ]

    out_path = tmp_path / "web.json"
    write_json(root, images, str(out_path))

    payload = json.loads(out_path.read_text())
    assert "location" not in payload["tree"]
    assert payload["tree"]["children"][0]["location"] == _LOCATION
    assert "location" not in payload["tree"]["children"][1]
    assert payload["images"][0]["location"] == _LOCATION
    assert "location" not in payload["images"][1]


def test_write_json_keeps_emphasis_and_drops_it_when_empty(tmp_path):
    styled = WebNode(
        type="Clause", identifier="(a)", citation="c", title="", path="", content="a building"
    )
    styled.emphasis = [[2, 10, "i"]]
    root = WebNode(
        type="root", identifier="", citation="root", title="", path="", children=[styled]
    )

    out_path = tmp_path / "web_toc.json"
    write_json(root, [], str(out_path))

    payload = json.loads(out_path.read_text())
    assert payload["tree"]["children"][0]["emphasis"] == [[2, 10, "i"]]
    assert "emphasis" not in payload["tree"]
