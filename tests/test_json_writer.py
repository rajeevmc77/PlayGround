import json

from mo_toc.domain.models import BBox, Caption, ImageAsset, Node
from mo_toc.output.json_writer import write_json


def test_write_json_roundtrips_tree_shape(tmp_path):
    child = Node(type="Part", identifier="1", citation="A-1", title="",
                 page=2, end_page=3, bbox=BBox(0, 0, 10, 10))
    root = Node(type="Volume", identifier="Volume", citation="Volume", title="",
                page=1, end_page=10, bbox=BBox(0, 0, 0, 0), children=[child])
    caption = Caption(kind="Figure", identifier="1-A", title="Foo", page=3,
                       bbox=BBox(0, 0, 5, 5), owner_citation="A-1", forming_part_of=None,
                       continuation=False)
    image = ImageAsset(page=3, bbox=BBox(0, 0, 5, 5), width=5, height=5, phash="abc",
                        thumbnail_path="thumbnails/img_0.png")

    out_path = tmp_path / "out.json"
    write_json(root, [caption], [image], str(out_path))

    payload = json.loads(out_path.read_text())
    assert payload["volume"]["type"] == "Volume"
    assert payload["volume"]["children"][0]["citation"] == "A-1"
    assert payload["captions"][0]["identifier"] == "1-A"
    assert payload["images"][0]["phash"] == "abc"


def test_write_json_creates_parent_directories(tmp_path):
    root = Node(type="Volume", identifier="Volume", citation="Volume", title="",
                page=1, end_page=1, bbox=BBox(0, 0, 0, 0))
    out_path = tmp_path / "nested" / "out.json"
    write_json(root, [], [], str(out_path))
    assert out_path.exists()
