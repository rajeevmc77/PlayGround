from mo_toc.output.image_writer import write_images
from mo_toc.parsing.image_extractor import RawImage


def _raw(page=1, ext="png", data=b"\x89PNG\r\n\x1a\nfake"):
    return RawImage(
        page=page, bbox=(0, 0, 10, 10), width=10, height=10, data=data, ext=ext, phash="abc"
    )


def test_writes_one_file_per_image(tmp_path):
    output_dir = tmp_path / "images"
    assets = write_images([_raw(), _raw(page=2)], str(output_dir))
    assert (output_dir / "img_0.png").exists()
    assert (output_dir / "img_1.png").exists()
    assert len(assets) == 2


def test_asset_image_path_is_relative_to_output_dir_parent(tmp_path):
    output_dir = tmp_path / "images"
    assets = write_images([_raw()], str(output_dir))
    assert assets[0].image_path == "images/img_0.png"


def test_asset_carries_page_bbox_dimensions_phash(tmp_path):
    output_dir = tmp_path / "images"
    assets = write_images([_raw(page=5)], str(output_dir))
    asset = assets[0]
    assert asset.page == 5
    assert (asset.width, asset.height) == (10, 10)
    assert asset.phash == "abc"


def test_empty_list_writes_nothing(tmp_path):
    output_dir = tmp_path / "images"
    assert write_images([], str(output_dir)) == []
