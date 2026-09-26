from comparison.asset_loader import load_pdf_image_bytes, load_web_image_bytes


def test_loads_pdf_image_bytes_relative_to_the_output_dir(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "img_0.png").write_bytes(b"pdf-bytes")

    result = load_pdf_image_bytes(tmp_path, {"image_path": "images/img_0.png"})

    assert result == b"pdf-bytes"


def test_returns_none_when_the_pdf_image_file_is_missing(tmp_path):
    assert load_pdf_image_bytes(tmp_path, {"image_path": "images/missing.png"}) is None


def test_loads_web_image_bytes_relative_to_the_output_dir(tmp_path):
    (tmp_path / "web_images").mkdir()
    (tmp_path / "web_images" / "fig.jpg").write_bytes(b"web-bytes")

    result = load_web_image_bytes(tmp_path, {"local_path": "web_images/fig.jpg"})

    assert result == b"web-bytes"


def test_returns_none_when_local_path_is_empty():
    assert load_web_image_bytes("/anything", {"local_path": ""}) is None


def test_returns_none_when_the_web_image_file_is_missing(tmp_path):
    assert load_web_image_bytes(tmp_path, {"local_path": "web_images/missing.jpg"}) is None
