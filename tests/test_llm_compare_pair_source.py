import pytest

from llm_compare.domain.models import PdfLocation, WebLocation
from llm_compare.parsing.pair_source import build_pairs


def _pdf(number, path):
    image = {"image_path": path}
    if number:
        image["unified_number"] = number
    return image


def _web(number, path, image_id=None):
    return {"unified_number": number, "local_path": path, "id": image_id or number}


def test_a_same_numbered_pair_is_comparable():
    (pair,) = build_pairs(
        [_pdf("A.Fig1", "images/1.png")], [_web("A.Fig1", "web_images/1.jpg")], {}
    )
    assert (pair.key, pair.pdf_path, pair.web_path, pair.web_key) == (
        "A.Fig1",
        "images/1.png",
        "web_images/1.jpg",
        "A.Fig1",
    )
    assert pair.skip_reason == "" and pair.row_id == "pdf:images/1.png"


def test_a_counterpart_overrides_the_same_number():
    pdf = [_pdf("A.Fig1", "images/1.png")]
    web = [_web("A.Fig1", "web_images/a.jpg"), _web("A.Eq2", "web_images/b.jpg")]
    pairs = build_pairs(pdf, web, {"A.Fig1": "A.Eq2"})
    assert pairs[0].web_key == "A.Eq2" and pairs[0].web_path == "web_images/b.jpg"
    assert [p.key for p in pairs] == ["A.Fig1", "A.Fig1"]  # the unused A.Fig1 web image is web-only
    assert pairs[1].pdf_path is None and pairs[1].web_path == "web_images/a.jpg"


def test_a_null_counterpart_or_missing_web_image_is_skipped():
    pdf = [_pdf("A.Fig1", "images/1.png"), _pdf("A.Fig2", "images/2.png")]
    pairs = build_pairs(pdf, [], {"A.Fig1": None})
    assert [p.skip_reason for p in pairs] == ["no web counterpart", "no web counterpart"]
    assert all(p.web_path is None for p in pairs)


def test_a_pdf_image_without_a_number_is_skipped_and_keyed_by_its_path():
    (pair,) = build_pairs([_pdf(None, "images/9.png")], [], {})
    assert pair.key == "images/9.png" and pair.skip_reason == "no unified number"


def test_a_web_image_without_a_local_file_is_skipped():
    web = [{"unified_number": "A.Fig1", "id": "x", "local_path": ""}]
    (pair,) = build_pairs([_pdf("A.Fig1", "images/1.png")], web, {})
    assert pair.skip_reason == "web image has no local file" and pair.web_path is None


def test_web_images_no_pdf_image_pairs_with_become_web_only_rows():
    web = [_web("A.Fig1", "web_images/1.jpg"), _web("Z.Fig9", "web_images/z.jpg")]
    pairs = build_pairs([_pdf("A.Fig1", "images/1.png")], web, {})
    assert len(pairs) == 2
    only = pairs[1]
    assert (only.key, only.pdf_path, only.web_path) == ("Z.Fig9", None, "web_images/z.jpg")
    assert only.row_id == "web:web_images/z.jpg"


def test_a_web_image_without_a_number_is_keyed_by_its_id():
    web = [{"id": "nbc.x.figure1", "local_path": "web_images/x.jpg"}]
    (pair,) = build_pairs([], web, {})
    assert pair.key == "nbc.x.figure1"


def test_two_pdf_images_can_share_one_web_image_and_it_is_not_web_only():
    pdf = [_pdf("A.Fig1", "images/1.png"), _pdf("A.Fig2", "images/2.png")]
    web = [_web("A.Eq1", "web_images/e.jpg")]
    pairs = build_pairs(pdf, web, {"A.Fig1": "A.Eq1", "A.Fig2": "A.Eq1"})
    assert len(pairs) == 2 and all(p.web_key == "A.Eq1" for p in pairs)


def test_row_ids_are_unique_even_when_keys_repeat():
    pdf = [_pdf("A.Fig1", "images/1.png")]
    web = [_web("A.Fig1", "web_images/1.jpg", "w1"), _web("Q.Fig1", "web_images/q.jpg")]
    ids = [p.row_id for p in build_pairs(pdf, web, {"A.Fig1": None})]
    assert len(ids) == len(set(ids))


# ---- locations ----------------------------------------------------------------------------

BOX = {"x0": 91.0, "y0": 72.5, "x1": 481.0, "y1": 252.0}
WEB_LOCATION = {
    "page_file": "web_pages/nbc.html",
    "xpath": "/html/body/main/div/main/img[1]",
    "bbox": {"x0": 488, "y0": 1530.45, "x1": 988, "y1": 1816.98},
}


def _located_pdf(number, path, page=40):
    return {**_pdf(number, path), "page": page, "bbox": BOX}


def _located_web(number, path, image_id="nbc.a.fig1"):
    return {**_web(number, path, image_id), "location": WEB_LOCATION}


def test_a_paired_row_carries_where_each_image_sits_in_the_pdf_and_the_saved_page():
    (pair,) = build_pairs(
        [_located_pdf("A.Fig1", "images/1.png")], [_located_web("A.Fig1", "web_images/1.jpg")], {}
    )
    assert pair.pdf_location == PdfLocation(40, 91.0, 72.5, 481.0, 252.0)
    assert pair.web_location == WebLocation(
        "web_pages/nbc.html",
        "/html/body/main/div/main/img[1]",
        488,
        1530.45,
        988,
        1816.98,
        "nbc.a.fig1",
    )


def test_a_pdf_only_skipped_row_keeps_its_pdf_location_only():
    (pair,) = build_pairs([_located_pdf("A.Fig1", "images/1.png")], [], {})
    assert pair.skip_reason and pair.web_location is None
    assert pair.pdf_location.page == 40


def test_a_pdf_image_without_a_number_still_has_its_location():
    (pair,) = build_pairs([_located_pdf(None, "images/1.png", page=7)], [], {})
    assert pair.skip_reason == "no unified number" and pair.pdf_location.page == 7


def test_a_web_only_row_carries_its_web_location_only():
    pairs = build_pairs([], [_located_web("A.Fig1", "web_images/1.jpg")], {})
    assert pairs[0].pdf_location is None and pairs[0].web_location.element_id == "nbc.a.fig1"


def test_a_web_image_without_a_local_file_keeps_both_locations():
    web = {**_located_web("A.Fig1", ""), "local_path": ""}
    (pair,) = build_pairs([_located_pdf("A.Fig1", "images/1.png")], [web], {})
    assert pair.skip_reason and pair.pdf_location and pair.web_location


def test_entries_without_a_location_have_none():
    (pair,) = build_pairs(
        [_pdf("A.Fig1", "images/1.png")], [_web("A.Fig1", "web_images/1.jpg")], {}
    )
    assert pair.pdf_location is None and pair.web_location is None


@pytest.mark.parametrize(
    "broken",
    [
        {"page": 3},
        {"bbox": BOX},
        {"page": "x", "bbox": BOX},
        {"page": 3, "bbox": {"x0": 1}},
        {"page": 3, "bbox": "nope"},
        {"page": True, "bbox": BOX},
    ],
)
def test_a_malformed_pdf_location_is_dropped_not_fatal(broken):
    (pair,) = build_pairs([{**_pdf("A.Fig1", "images/1.png"), **broken}], [], {})
    assert pair.pdf_location is None


@pytest.mark.parametrize(
    "broken",
    [
        "nope",
        {"page_file": "p.html"},
        {"page_file": "p.html", "xpath": "/x", "bbox": {"x0": 1}},
        {"page_file": "", "xpath": "/x", "bbox": WEB_LOCATION["bbox"]},
    ],
)
def test_a_malformed_web_location_is_dropped_not_fatal(broken):
    web = {**_web("A.Fig1", "web_images/1.jpg"), "location": broken}
    (pair,) = build_pairs([], [web], {})
    assert pair.web_location is None
