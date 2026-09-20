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


def test_write_json_creates_parent_directories(tmp_path):
    root = WebNode(type="root", identifier="", citation="root", title="", path="/")
    out_path = tmp_path / "nested" / "web_toc.json"
    write_json(root, [], str(out_path))
    assert out_path.exists()
