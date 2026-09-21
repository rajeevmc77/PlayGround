from mo_toc.domain.models import BBox, Caption, ImageAsset, Node


def test_bbox_as_tuple():
    box = BBox(1.0, 2.0, 3.0, 4.0)
    assert box.as_tuple() == (1.0, 2.0, 3.0, 4.0)


def test_node_defaults_to_no_children():
    node = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=10,
        bbox=BBox(0, 0, 0, 0),
    )
    assert node.children == []


def test_node_children_are_independent_between_instances():
    a = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="",
        page=7,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
    )
    b = Node(
        type="Part",
        identifier="2",
        citation="A-2",
        title="",
        page=9,
        end_page=10,
        bbox=BBox(0, 0, 0, 0),
    )
    a.children.append("x")
    assert b.children == []


def test_node_unified_number_defaults_to_empty_string():
    node = Node(
        type="Division",
        identifier="A",
        citation="A",
        title="",
        page=6,
        end_page=10,
        bbox=BBox(0, 0, 0, 0),
    )
    assert node.unified_number == ""


def test_node_unified_number_can_be_set():
    node = Node(
        type="Part",
        identifier="1",
        citation="A-1",
        title="",
        page=7,
        end_page=8,
        bbox=BBox(0, 0, 0, 0),
        unified_number="1.1",
    )
    assert node.unified_number == "1.1"


def test_caption_forming_part_of_can_be_none():
    cap = Caption(
        kind="Figure",
        identifier="1.1.1.1.-A",
        title="Foo",
        page=10,
        bbox=BBox(0, 0, 0, 0),
        owner_citation="A-1.1.1.1.",
        forming_part_of=None,
        continuation=False,
    )
    assert cap.forming_part_of is None


def test_image_asset_holds_pixel_size_and_thumbnail_path():
    img = ImageAsset(
        page=10,
        bbox=BBox(0, 0, 100, 50),
        width=100,
        height=50,
        phash="abc123",
        thumbnail_path="thumbnails/img_0.png",
    )
    assert (img.width, img.height) == (100, 50)
    assert img.thumbnail_path == "thumbnails/img_0.png"


def test_image_asset_owner_and_caption_fields_default_unset():
    img = ImageAsset(
        page=10,
        bbox=BBox(0, 0, 100, 50),
        width=100,
        height=50,
        phash="abc123",
        thumbnail_path="thumbnails/img_0.png",
    )
    assert img.owner_citation == ""
    assert img.caption_kind is None
    assert img.caption_identifier is None


def test_image_asset_owner_and_caption_fields_can_be_set():
    img = ImageAsset(
        page=37,
        bbox=BBox(0, 0, 10, 10),
        width=10,
        height=10,
        phash=None,
        thumbnail_path="thumbnails/img_1.png",
        owner_citation="Note:A-1.3.3.4",
        caption_kind="Figure",
        caption_identifier="A-1.3.3.4.(2)",
    )
    assert img.owner_citation == "Note:A-1.3.3.4"
    assert img.caption_kind == "Figure"
    assert img.caption_identifier == "A-1.3.3.4.(2)"
