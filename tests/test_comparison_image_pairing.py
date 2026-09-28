"""image_counterparts pairs a provision's PDF images with its web images by
where they stand, not by their FigN/EqN numbers, when the two sides label
them differently: the PDF reads 4.1.6.5.'s stacked two-line formula as a
figure, the site as an equation, so by number every image after it met the
wrong partner. Only non-table images of one provision pair this way - a
table's images keep their numbers."""

from comparison.image_pairing import image_counterparts


def _pdf(number, page, y, x=100):
    return {
        "unified_number": number,
        "page": page,
        "bbox": {"x0": x, "y0": y, "x1": x + 50, "y1": y + 20},
    }


def _web(number, y, image_id="nbc.art5.sent1.eg1"):
    return {
        "unified_number": number,
        "id": image_id,
        "location": {
            "page_file": "web_pages/p.html",
            "bbox": {"x0": 0, "y0": y, "x1": 10, "y1": y},
        },
    }


TREE = {"unified_number": "V", "children": []}


def test_a_provisions_images_labelled_differently_pair_by_where_they_stand():
    pdf = [
        _pdf("A.Eq1", 1, 100),
        _pdf("A.Fig1", 1, 200),
        _pdf("A.Eq2", 1, 300),
        _pdf("A.Fig2", 2, 50),
    ]
    web = [_web("A.Eq1", 10), _web("A.Eq2", 20), _web("A.Eq3", 30), _web("A.Fig1", 40)]
    assert image_counterparts(TREE, pdf, web) == {
        "A.Fig1": "A.Eq2",
        "A.Eq2": "A.Eq3",
        "A.Fig2": "A.Fig1",
    }


def test_images_already_paired_by_number_record_nothing():
    pdf = [_pdf("A.Eq1", 1, 100), _pdf("A.Fig1", 1, 200)]
    web = [_web("A.Eq1", 10), _web("A.Fig1", 20)]
    assert image_counterparts(TREE, pdf, web) == {}


def test_a_provision_with_more_images_on_one_side_keeps_its_numbers():
    pdf = [_pdf("A.Fig1", 1, 100), _pdf("A.Eq1", 1, 200)]
    web = [_web("A.Eq1", 10), _web("A.Eq2", 20), _web("A.Fig1", 30)]
    assert image_counterparts(TREE, pdf, web) == {}


def test_images_never_pair_across_provisions():
    pdf = [_pdf("A.Fig1", 1, 100), _pdf("B.Eq1", 1, 200)]
    web = [_web("A.Eq1", 10), _web("B.Fig1", 20)]
    assert image_counterparts(TREE, pdf, web) == {"A.Fig1": "A.Eq1", "B.Eq1": "B.Fig1"}


def test_a_tables_images_keep_their_numbers():
    cell = {
        "unified_number": "A.Tbl1.Row1.Col1",
        "type": "Cell",
        "page": 1,
        "bbox": {"x0": 90, "y0": 90, "x1": 200, "y1": 400},
        "children": [],
    }
    tree = {"unified_number": "V", "children": [cell]}
    pdf = [_pdf("A.Fig1", 1, 100), _pdf("A.Eq1", 1, 300)]
    web = [
        _web("A.Eq1", 10, "nbc.art5.table1.eg1"),
        _web("A.Fig1", 20, "nbc.art5.table1.row1.figure1"),
    ]
    assert image_counterparts(tree, pdf, web) == {}
