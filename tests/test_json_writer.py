import json

from mo_toc.domain.models import BBox, Caption, ImageAsset, Node
from mo_toc.output.json_writer import write_json


def test_write_json_roundtrips_tree_shape(tmp_path):
    child = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="",
        page=2,
        end_page=3,
        bbox=BBox(0, 0, 10, 10),
    )
    root = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=10,
        bbox=BBox(0, 0, 0, 0),
        children=[child],
    )
    caption = Caption(
        kind="Figure",
        identifier="1-A",
        title="Foo",
        page=3,
        bbox=BBox(0, 0, 5, 5),
        owner_citation="A-1",
        forming_part_of=None,
        continuation=False,
    )
    image = ImageAsset(
        page=3,
        bbox=BBox(0, 0, 5, 5),
        width=5,
        height=5,
        phash="abc",
        image_path="images/img_0.png",
    )

    out_path = tmp_path / "out.json"
    write_json(root, [caption], [image], str(out_path))

    payload = json.loads(out_path.read_text())
    assert payload["volume"]["type"] == "Volume"
    assert payload["volume"]["children"][0]["citation"] == "A-1"
    assert payload["captions"][0]["identifier"] == "1-A"
    assert payload["images"][0]["phash"] == "abc"


def test_write_json_creates_parent_directories(tmp_path):
    root = Node(
        type="Volume",
        identifier="Volume",
        citation="Volume",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    out_path = tmp_path / "nested" / "out.json"
    write_json(root, [], [], str(out_path))
    assert out_path.exists()


def test_write_json_drops_title_for_content_bearing_types(tmp_path):
    sentence = Node(
        type="Sentence",
        identifier="(1)",
        citation="A-1.1.1.1.(1)",
        title="",
        content="Full text.",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    article = Node(
        type="Article",
        identifier="1.1.1.1.",
        citation="A-1.1.1.1.",
        title="A title",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
        children=[sentence],
    )
    out_path = tmp_path / "out.json"
    write_json(article, [], [], str(out_path))
    payload = json.loads(out_path.read_text())

    sentence_json = payload["volume"]["children"][0]
    assert "title" not in sentence_json
    assert sentence_json["content"] == "Full text."
    assert "content" not in payload["volume"]
    assert payload["volume"]["title"] == "A title"


def test_write_json_keeps_emphasis_on_content_bearing_types_only(tmp_path):
    clause = Node(
        type="Clause",
        identifier="(a)",
        citation="c",
        title="",
        content="a building",
        emphasis=[(2, 10, "i")],
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    part = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
        children=[clause],
    )
    out_path = tmp_path / "out.json"
    write_json(part, [], [], str(out_path))
    payload = json.loads(out_path.read_text())

    assert payload["volume"]["children"][0]["emphasis"] == [[2, 10, "i"]]
    assert "emphasis" not in payload["volume"]


def test_write_json_drops_both_title_and_content_for_row(tmp_path):
    row = Node(
        type="Row",
        identifier="Row1",
        citation="Table:1.1.(1)-Row1",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    out_path = tmp_path / "out.json"
    write_json(row, [], [], str(out_path))
    payload = json.loads(out_path.read_text())
    assert "title" not in payload["volume"]
    assert "content" not in payload["volume"]


def test_empty_heading_is_pruned_but_real_heading_kept(tmp_path):
    sentence = Node(
        type="Sentence",
        identifier="(1)",
        citation="s",
        title="",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
    )
    part = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="Compliance",
        page=1,
        end_page=1,
        bbox=BBox(0, 0, 0, 0),
        children=[sentence],
        heading="Part 1",
    )
    out = tmp_path / "out.json"

    write_json(part, [], [], str(out))

    payload = json.loads(out.read_text())["volume"]
    assert payload["heading"] == "Part 1"
    assert "heading" not in payload["children"][0]
