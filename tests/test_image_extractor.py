import io
from unittest.mock import MagicMock

from PIL import Image

from mo_toc.parsing.image_extractor import extract_images, vector_images_on_page
from mo_toc.parsing.pdf_source import ExtractedImage, PageImageInfo, PageLine


def _png_bytes(size=(10, 10), color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeImageSource:
    def __init__(
        self, pages_images: dict[int, list[PageImageInfo]], pages_drawings=None, pages_lines=None
    ):
        self._pages_images = pages_images
        self._pages_drawings = pages_drawings or {}
        self._pages_lines = pages_lines or {}
        self._xref_bytes = {}

    @property
    def page_count(self):
        pages = list(self._pages_images) + list(self._pages_drawings) + list(self._pages_lines)
        return max(pages) + 1 if pages else 0

    def page_lines(self, page_index):
        return self._pages_lines.get(page_index, [])

    def page_images(self, page_index):
        return self._pages_images.get(page_index, [])

    def register_image(self, xref, data, ext="png", width=10, height=10):
        self._xref_bytes[xref] = ExtractedImage(data=data, ext=ext, width=width, height=height)

    def extract_image(self, xref):
        return self._xref_bytes[xref]

    def page_drawing_rects(self, page_index):
        return self._pages_drawings.get(page_index, [])

    def render_region(self, page_index, bbox):
        return ExtractedImage(data=_png_bytes(), ext="png", width=30, height=30)


def test_extracts_every_image_no_size_filter():
    source = FakeImageSource({0: [PageImageInfo(bbox=(0, 0, 5, 5), xref=1)]})
    source.register_image(1, _png_bytes(), width=5, height=5)
    images = extract_images(source)
    assert len(images) == 1
    assert (images[0].width, images[0].height) == (5, 5)
    assert images[0].page == 1


def test_extracts_multiple_images_across_pages():
    source = FakeImageSource(
        {
            0: [PageImageInfo(bbox=(0, 0, 100, 100), xref=1)],
            1: [
                PageImageInfo(bbox=(0, 0, 50, 50), xref=2),
                PageImageInfo(bbox=(60, 0, 80, 20), xref=3),
            ],
        }
    )
    source.register_image(1, _png_bytes())
    source.register_image(2, _png_bytes())
    source.register_image(3, _png_bytes())
    images = extract_images(source)
    assert [img.page for img in images] == [1, 2, 2]


def test_computes_phash_from_image_bytes():
    source = FakeImageSource({0: [PageImageInfo(bbox=(0, 0, 10, 10), xref=1)]})
    source.register_image(1, _png_bytes())
    images = extract_images(source)
    assert images[0].phash is not None
    assert len(images[0].phash) > 0


def test_no_images_returns_empty_list():
    source = FakeImageSource({})
    assert extract_images(source) == []


def test_phash_none_when_image_bytes_are_invalid():
    source = FakeImageSource({0: [PageImageInfo(bbox=(0, 0, 10, 10), xref=1)]})
    source.register_image(1, b"not a real image")
    images = extract_images(source)
    assert images[0].phash is None


def test_vector_only_figure_is_extracted_as_an_image():
    source = FakeImageSource({}, pages_drawings={0: [(0, 0, 100, 100)]})
    images = extract_images(source)
    assert len(images) == 1
    assert images[0].page == 1
    assert images[0].bbox == (0, 0, 100, 100)


def test_vector_cluster_overlapping_a_raster_image_is_not_duplicated():
    source = FakeImageSource(
        {0: [PageImageInfo(bbox=(0, 0, 50, 50), xref=1)]},
        pages_drawings={0: [(10, 10, 40, 40)]},
    )
    source.register_image(1, _png_bytes())
    images = extract_images(source)
    assert len(images) == 1


def test_thin_rule_lines_are_not_extracted_as_images():
    source = FakeImageSource({}, pages_drawings={0: [(0, 0, 400, 0.5)]})
    assert extract_images(source) == []


def _fake_source(rendered_bbox_capture):
    source = MagicMock()

    def render_region(page_index, bbox):
        rendered_bbox_capture.append(bbox)
        return ExtractedImage(data=b"x", ext="png", width=1, height=1)

    source.render_region.side_effect = render_region
    return source


def test_vector_images_on_page_excludes_table_bboxes():
    # A vector cluster that exactly matches a detected table's outer bbox
    # must not be rendered as a "figure" - it's a table border, not an image.
    rects = [(90.0, 90.0, 90.5, 400.0), (90.0, 400.0, 500.0, 400.5)]  # forms a >400pt^2 cluster
    rendered = []
    source = _fake_source(rendered)
    table_bboxes = [(85.0, 85.0, 505.0, 405.0)]  # overlaps the cluster fully

    result = vector_images_on_page(
        source, 0, raster_bboxes=[], drawing_rects=rects, table_bboxes=table_bboxes
    )

    assert result == []
    assert rendered == []


def test_vector_images_on_page_still_renders_clusters_outside_table_bboxes():
    rects = [(90.0, 90.0, 90.5, 400.0), (90.0, 400.0, 500.0, 400.5)]
    rendered = []
    source = _fake_source(rendered)

    result = vector_images_on_page(
        source, 0, raster_bboxes=[], drawing_rects=rects, table_bboxes=[]
    )

    assert len(result) == 1
    assert len(rendered) == 1


CAPTION_FONT = "Arial-BoldMT"
BODY_FONT = "ArialMT"


def _table_grid_fixture():
    # Mirrors tests/test_table_extractor.py's _minimal_grid_fixture: a genuine
    # Table caption plus vector-drawn gridlines that form a real table border -
    # the same border that used to get misclassified and rendered as a "figure".
    lines = [
        PageLine(bbox=(200, 10, 300, 20), text="Table 1.1.(1)", font=CAPTION_FONT),
        PageLine(bbox=(150, 22, 350, 32), text="Sample Title", font=CAPTION_FONT),
        PageLine(bbox=(90, 50, 110, 60), text="No.", font=CAPTION_FONT),
        PageLine(bbox=(120, 50, 250, 60), text="Description", font=CAPTION_FONT),
        PageLine(bbox=(90, 70, 110, 80), text="1", font=BODY_FONT),
        PageLine(bbox=(120, 70, 250, 80), text="First row content.", font=BODY_FONT),
    ]
    rects = [
        (90.0, 45.0, 260.0, 45.4),  # top border
        (90.0, 45.0, 90.4, 90.0),  # left border
        (259.6, 45.0, 260.0, 90.0),  # right border
        (90.0, 65.0, 260.0, 65.4),  # header/body divider
        (90.0, 89.6, 260.0, 90.0),  # bottom border
        (114.6, 45.0, 115.0, 90.0),  # column divider
    ]
    return lines, rects


def test_extract_images_excludes_a_detected_table_region_from_vector_clustering():
    # Same bug as test_vector_images_on_page_excludes_table_bboxes, but proven
    # through the sequential extract_images() entry point end-to-end: without
    # table detection wired in here too, these gridlines cluster into one
    # >400pt^2 vector "figure" and get rendered as an image.
    lines, rects = _table_grid_fixture()
    source = FakeImageSource({}, pages_drawings={0: rects}, pages_lines={0: lines})

    images = extract_images(source)

    assert images == []


def _caption_less_grid_rects():
    # Real-document shape (Table 1.1.1.1.(5)'s continuation tail, page 12):
    # a multi-row, multi-column grid of thin gridline rects with NO "Table X"
    # caption line anywhere on the page, so detect_tables_on_page finds zero
    # anchors/regions here - table_bboxes is empty, unlike
    # test_extract_images_excludes_a_detected_table_region_from_vector_clustering.
    rects = []
    for row_y in (45.0, 65.0, 85.0, 105.0):
        rects.append((90.0, row_y, 260.0, row_y + 0.4))
    for col_x in (90.0, 175.0, 260.0):
        rects.append((col_x, 45.0, col_x + 0.4, 105.0))
    return rects


def test_vector_images_on_page_excludes_a_caption_less_table_grid():
    rects = _caption_less_grid_rects()
    rendered = []
    source = _fake_source(rendered)

    result = vector_images_on_page(
        source, 0, raster_bboxes=[], drawing_rects=rects, table_bboxes=[]
    )

    assert result == []
    assert rendered == []


def test_extract_images_excludes_a_caption_less_table_grid_end_to_end():
    # Confirmed real bug: Table 1.1.1.1.(5)'s continuation tail has no
    # caption of its own (it shares page 12 with Table 1.1.1.1.(6)'s
    # caption instead - see table_extractor.fill_continuation_gaps's
    # docstring), so it was never excluded by the table-bbox check alone
    # and leaked through as a spurious vector "figure" attached to a
    # sentence in the viewer.
    rects = _caption_less_grid_rects()
    source = FakeImageSource({}, pages_drawings={0: rects}, pages_lines={0: []})

    images = extract_images(source)

    assert images == []
