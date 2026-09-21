import io

from PIL import Image

from mo_toc.parsing.image_extractor import extract_images
from mo_toc.parsing.pdf_source import ExtractedImage, PageImageInfo


def _png_bytes(size=(10, 10), color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeImageSource:
    def __init__(self, pages_images: dict[int, list[PageImageInfo]], pages_drawings=None):
        self._pages_images = pages_images
        self._pages_drawings = pages_drawings or {}
        self._xref_bytes = {}

    @property
    def page_count(self):
        pages = list(self._pages_images) + list(self._pages_drawings)
        return max(pages) + 1 if pages else 0

    def page_lines(self, page_index):
        return []

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
