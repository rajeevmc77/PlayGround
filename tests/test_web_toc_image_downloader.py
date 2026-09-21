import asyncio
import time
from unittest.mock import AsyncMock

from web_toc.domain.models import WebImage
from web_toc.output.image_downloader import download_images


def _image(id_="nbc.divA.part1.figure1", src="bc-graphics/gg00556a"):
    return WebImage(id=id_, src=src, alt_text="A diagram", owner_citation="nbc.divA.part1")


def _run(coro):
    return asyncio.run(coro)


def test_writes_one_file_per_image_and_sets_local_path(tmp_path):
    output_dir = tmp_path / "web_images"
    source = AsyncMock()
    source.fetch_image.return_value = b"fakejpegbytes"
    img = _image()

    _run(download_images([img], source, str(output_dir)))

    expected_file = output_dir / "nbc.divA.part1.figure1.jpg"
    assert expected_file.exists()
    assert expected_file.read_bytes() == b"fakejpegbytes"
    assert img.local_path == "web_images/nbc.divA.part1.figure1.jpg"


def test_source_is_asked_for_the_images_own_src(tmp_path):
    source = AsyncMock()
    source.fetch_image.return_value = b"bytes"
    img = _image(src="bc-graphics/some-figure")

    _run(download_images([img], source, str(tmp_path / "web_images")))

    source.fetch_image.assert_called_once_with("bc-graphics/some-figure")


def test_skips_image_with_empty_src(tmp_path):
    source = AsyncMock()
    img = _image(src="")

    _run(download_images([img], source, str(tmp_path / "web_images")))

    source.fetch_image.assert_not_called()
    assert img.local_path == ""


def test_failed_download_is_skipped_not_fatal(tmp_path):
    output_dir = tmp_path / "web_images"
    source = AsyncMock()
    source.fetch_image.return_value = None
    img = _image()

    _run(download_images([img], source, str(output_dir)))

    assert img.local_path == ""
    assert not (output_dir / "nbc.divA.part1.figure1.jpg").exists()


def test_empty_list_writes_nothing(tmp_path):
    output_dir = tmp_path / "web_images"
    source = AsyncMock()

    _run(download_images([], source, str(output_dir)))

    source.fetch_image.assert_not_called()


def test_downloads_multiple_images_concurrently(tmp_path):
    output_dir = tmp_path / "web_images"
    source = AsyncMock()

    async def _slow_fetch(src):
        await asyncio.sleep(0.2)
        return f"bytes-for-{src}".encode()

    source.fetch_image.side_effect = _slow_fetch
    images = [_image(id_=f"nbc.divA.part1.figure{n}", src=f"bc-graphics/g{n}") for n in range(6)]

    start = time.monotonic()
    _run(download_images(images, source, str(output_dir)))
    elapsed = time.monotonic() - start

    assert elapsed < 0.2 * len(images), (
        f"expected concurrent downloads to run faster than serial "
        f"({0.2 * len(images)}s), took {elapsed}s"
    )
    for img in images:
        expected_file = output_dir / f"{img.id}.jpg"
        assert expected_file.read_bytes() == f"bytes-for-{img.src}".encode()
        assert img.local_path == f"web_images/{img.id}.jpg"
