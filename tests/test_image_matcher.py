from mo_toc.domain.models import BBox, Caption, ImageAsset, Node
from mo_toc.parsing.image_matcher import match_images


def _node(node_type, identifier, citation, page, end_page, children=None):
    return Node(
        type=node_type,
        identifier=identifier,
        citation=citation,
        title="",
        page=page,
        end_page=end_page,
        bbox=BBox(0, 0, 0, 0),
        children=children or [],
    )


def _image(page, y0, y1, x0=100, x1=200):
    return ImageAsset(
        page=page,
        bbox=BBox(x0, y0, x1, y1),
        width=int(x1 - x0),
        height=int(y1 - y0),
        phash=None,
        image_path=f"images/img_p{page}_{y0}.png",
    )


def _caption(kind, identifier, page, y0, y1, x0=100, x1=200, title="Some title"):
    return Caption(
        kind=kind,
        identifier=identifier,
        title=title,
        page=page,
        bbox=BBox(x0, y0, x1, y1),
        owner_citation="",
        forming_part_of=None,
        continuation=False,
    )


def _tree():
    article = _node("Article", "1.1.1.1.", "A-1.1.1.1.", page=10, end_page=12)
    part = _node("Part", "1", "A-1", page=7, end_page=20, children=[article])
    division = _node("Division", "A", "A", page=6, end_page=30, children=[part])
    return _node("Volume", "Volume", "Volume", page=1, end_page=30, children=[division])


def test_image_owner_is_deepest_node_containing_its_page():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    result = match_images([image], [], volume)
    assert result[0].owner_citation == "A-1.1.1.1."


def test_image_owner_extends_past_declared_end_page_when_no_next_sibling():
    # A node's end_page is a lossy page-level projection of "until the next
    # sibling opens" - it's not itself the source of truth. With no next
    # sibling to bound it, ownership legitimately extends past the node's
    # own declared end_page rather than falling back to a shallower parent -
    # this mirrors the live stack tree_builder itself uses for captions,
    # where a node stays "open" until something else opens, period.
    volume = _tree()
    image = _image(page=15, y0=100, y1=150)  # past Article's own end_page=12
    result = match_images([image], [], volume)
    assert result[0].owner_citation == "A-1.1.1.1."


def test_image_owner_stops_at_a_later_sibling_on_a_different_page():
    article1 = _node("Article", "1.1.1.1.", "A-1.1.1.1.", page=10, end_page=12)
    article2 = _node("Article", "1.1.1.2.", "A-1.1.1.2.", page=15, end_page=20)
    part = _node("Part", "1", "A-1", page=7, end_page=20, children=[article1, article2])
    division = _node("Division", "A", "A", page=6, end_page=30, children=[part])
    volume = _node("Volume", "Volume", "Volume", page=1, end_page=30, children=[division])

    before = _image(page=13, y0=100, y1=150)
    assert match_images([before], [], volume)[0].owner_citation == "A-1.1.1.1."

    after = _image(page=16, y0=50, y1=100)
    assert match_images([after], [], volume)[0].owner_citation == "A-1.1.1.2."


def test_image_owner_is_volume_when_outside_every_child_range():
    volume = _tree()
    image = _image(page=1, y0=100, y1=150)  # before Division starts
    result = match_images([image], [], volume)
    assert result[0].owner_citation == "Volume"


def test_image_owner_picks_nearest_preceding_sibling_when_several_share_a_page():
    # Confirmed real-document pattern: several Notes routinely land on one
    # page, all with page == end_page == that page (per the same-page-
    # siblings end_page clamp) - pure page-range containment can't tell them
    # apart, so the image's own y-position relative to each Note's own
    # heading y0 is what actually disambiguates which Note it belongs to.
    note_a = _node("Note", "A-1.3.3.4.(1)", "Note:A-1.3.3.4.(1)", page=37, end_page=37)
    note_a.bbox = BBox(0, 100, 0, 0)
    note_b = _node("Note", "A-1.3.3.4.(2)", "Note:A-1.3.3.4.(2)", page=37, end_page=37)
    note_b.bbox = BBox(0, 300, 0, 0)
    note_c = _node("Note", "A-1.4.1.2.(1)", "Note:A-1.4.1.2.(1)", page=37, end_page=37)
    note_c.bbox = BBox(0, 700, 0, 0)
    container = _node(
        "NotesContainer",
        "1",
        "Notes-A-1",
        page=37,
        end_page=37,
        children=[note_a, note_b, note_c],
    )
    volume = _node("Volume", "Volume", "Volume", page=1, end_page=37, children=[container])

    image_near_b = _image(page=37, y0=350, y1=450)
    result = match_images([image_near_b], [], volume)
    assert result[0].owner_citation == "Note:A-1.3.3.4.(2)"


def test_image_matched_to_caption_directly_below_on_same_page():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    caption = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=155, y1=170, title="Flight")
    result = match_images([image], [caption], volume)
    assert result[0].caption_kind == "Figure"
    assert result[0].caption_identifier == "A-1.1.1.1.-A"
    assert result[0].caption_title == "Flight"


def test_image_matched_to_caption_above_when_no_caption_below():
    volume = _tree()
    image = _image(page=11, y0=200, y1=250)
    caption = _caption("Table", "A-1.1.1.1.-B", page=11, y0=170, y1=190)
    result = match_images([image], [caption], volume)
    assert result[0].caption_kind == "Table"
    assert result[0].caption_identifier == "A-1.1.1.1.-B"


def test_image_not_matched_to_caption_on_different_page():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    caption = _caption("Figure", "A-1.1.1.1.-A", page=12, y0=155, y1=170)
    result = match_images([image], [caption], volume)
    assert result[0].caption_kind is None
    assert result[0].caption_identifier is None
    assert result[0].caption_title is None


def test_image_matched_to_caption_that_is_touching_or_slightly_overlapping():
    # Confirmed real-document case (page 37, Figure A-1.3.3.4.(2)): a
    # caption's own bbox top edge and the image's own bbox bottom edge can
    # be within ~1pt of each other, or even overlap by a hair (font-leading/
    # whitespace measurement slop), rather than having a clean positive
    # gap - still the obviously-correct pairing, not "no caption nearby."
    volume = _tree()
    image = _image(page=11, y0=72, y1=339.95)
    caption = _caption("Figure", "A-1.3.3.4.(2)", page=11, y0=338.8, y1=353.1)
    result = match_images([image], [caption], volume)
    assert result[0].caption_identifier == "A-1.3.3.4.(2)"


def test_image_not_matched_to_caption_too_far_away():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    caption = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=500, y1=520)
    result = match_images([image], [caption], volume)
    assert result[0].caption_kind is None
    assert result[0].caption_identifier is None


def test_two_images_each_claim_their_own_nearest_caption():
    volume = _tree()
    image_top = _image(page=11, y0=100, y1=150)
    image_bottom = _image(page=11, y0=300, y1=350)
    caption_top = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=155, y1=170)
    caption_bottom = _caption("Figure", "A-1.1.1.1.-B", page=11, y0=355, y1=370)
    result = match_images([image_top, image_bottom], [caption_top, caption_bottom], volume)
    by_y0 = {img.bbox.y0: img for img in result}
    assert by_y0[100].caption_identifier == "A-1.1.1.1.-A"
    assert by_y0[300].caption_identifier == "A-1.1.1.1.-B"


def test_original_image_fields_are_preserved():
    volume = _tree()
    image = _image(page=11, y0=100, y1=150)
    result = match_images([image], [], volume)
    assert result[0].width == image.width
    assert result[0].image_path == image.image_path


def test_empty_images_list_returns_empty_list():
    assert match_images([], [], _tree()) == []


def test_prefers_a_farther_figure_caption_over_a_closer_table_caption():
    # Confirmed real-document case (Article 4.1.6.5.'s Figure 4.1.6.5.-A
    # diagram): the genuine "Figure ..." caption introduces the diagram from
    # 48pt above it, while an unrelated "Table ..." caption - introducing the
    # data table that follows the diagram, not the diagram itself - sits only
    # 44pt below it. Pure nearest-distance picks the Table caption and
    # mislabels the diagram; images are never themselves tables (tables are
    # parsed as text, never as an embedded image), so a Figure-kind caption
    # is always the semantically correct pick when one is in range.
    volume = _tree()
    image = _image(page=11, y0=248, y1=498)
    figure_caption = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=200, y1=214)  # 34pt above
    table_caption = _caption("Table", "A-1.1.1.1.-B", page=11, y0=508, y1=522)  # 10pt below
    result = match_images([image], [figure_caption, table_caption], volume)
    assert result[0].caption_kind == "Figure"
    assert result[0].caption_identifier == "A-1.1.1.1.-A"


def test_falls_back_to_table_caption_when_no_figure_caption_is_in_range():
    volume = _tree()
    image = _image(page=11, y0=200, y1=250)
    table_caption = _caption("Table", "A-1.1.1.1.-B", page=11, y0=170, y1=190)
    result = match_images([image], [table_caption], volume)
    assert result[0].caption_kind == "Table"
    assert result[0].caption_identifier == "A-1.1.1.1.-B"


def test_nearest_figure_caption_wins_when_multiple_figure_captions_are_in_range():
    volume = _tree()
    image = _image(page=11, y0=200, y1=250)
    near = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=255, y1=270)
    far = _caption("Figure", "A-1.1.1.1.-B", page=11, y0=140, y1=155)
    result = match_images([image], [far, near], volume)
    assert result[0].caption_identifier == "A-1.1.1.1.-A"


def test_image_below_caption_eligibility_threshold_never_gets_a_caption():
    # An inline equation glyph (e.g. "xd = 5(CbSs/y)(Ca0-1)") is never itself
    # captioned in this document, but can still sit close enough to a real
    # Figure/Table caption to look like a match by distance alone. 40pt in
    # its smaller dimension matches the viewer's own "declutter" convention
    # for what counts as a real figure vs. a decorative/inline graphic.
    volume = _tree()
    tiny_image = _image(page=11, y0=100, y1=130, x0=100, x1=150)  # 50x30pt
    caption = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=135, y1=150)
    result = match_images([tiny_image], [caption], volume)
    assert result[0].caption_kind is None
    assert result[0].caption_identifier is None


def test_small_ineligible_image_does_not_steal_a_caption_from_a_farther_real_figure():
    # Confirmed real-document case (Article 4.1.6.5.'s Figure 4.1.6.5.-A): a
    # small equation-glyph image geometrically closer to the caption must not
    # win it over the actual (larger, farther) diagram the caption describes.
    volume = _tree()
    equation_glyph = _image(page=11, y0=126, y1=150, x0=100, x1=200)  # 100x24pt
    diagram = _image(page=11, y0=248, y1=498, x0=100, x1=400)  # 300x250pt
    figure_caption = _caption("Figure", "A-1.1.1.1.-A", page=11, y0=188, y1=202)
    table_caption = _caption("Table", "A-1.1.1.1.-B", page=11, y0=545, y1=559)

    result = match_images([equation_glyph, diagram], [figure_caption, table_caption], volume)

    by_y0 = {img.bbox.y0: img for img in result}
    assert by_y0[126].caption_identifier is None
    assert by_y0[248].caption_identifier == "A-1.1.1.1.-A"
    assert by_y0[248].caption_kind == "Figure"
