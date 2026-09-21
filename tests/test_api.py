import json

from fastapi.testclient import TestClient

from mo_toc.web.api import create_app


def _write_fixture_json(tmp_path):
    payload = {
        "volume": {
            "type": "Volume",
            "identifier": "Volume",
            "citation": "Volume",
            "title": "",
            "page": 1,
            "end_page": 10,
            "bbox": {"x0": 0, "y0": 0, "x1": 0, "y1": 0},
            "children": [],
        },
        "captions": [],
        "images": [
            {
                "page": 1,
                "bbox": {"x0": 0, "y0": 0, "x1": 5, "y1": 5},
                "width": 5,
                "height": 5,
                "phash": "abc",
                "image_path": "images/img_0.png",
            }
        ],
    }
    path = tmp_path / "mo_toc.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _make_client(tmp_path, pdf_path=None, create_image=True, web_toc_json_path=None):
    json_path = _write_fixture_json(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    if create_image:
        (images_dir / "img_0.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    if pdf_path is None:
        pdf_path = tmp_path / "sample.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
    app = create_app(
        toc_json_path=json_path,
        pdf_path=str(pdf_path),
        images_dir=str(images_dir),
        web_toc_json_path=web_toc_json_path,
    )
    return TestClient(app)


def test_get_toc_returns_volume_tree(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/toc")
    assert resp.status_code == 200
    assert resp.json()["type"] == "Volume"


def test_get_images_returns_list(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/images")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["phash"] == "abc"


def test_get_pdf_streams_file(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_get_image_by_index(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/image/0")
    assert resp.status_code == 200


def test_get_image_out_of_range_returns_404(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/image/99")
    assert resp.status_code == 404


def test_get_image_missing_file_returns_404(tmp_path):
    client = _make_client(tmp_path, create_image=False)
    resp = client.get("/api/image/0")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Image file missing"


def _write_web_toc_fixture(tmp_path, local_path=""):
    payload = {
        "tree": {
            "type": "root",
            "identifier": "",
            "citation": "root",
            "title": "",
            "path": "/",
            "children": [],
        },
        "images": [
            {
                "id": "fig1",
                "src": "bc-graphics/x",
                "alt_text": "alt",
                "owner_citation": "root",
                "local_path": local_path,
            }
        ],
    }
    path = tmp_path / "web_toc.json"
    path.write_text(json.dumps(payload))
    return str(path)


def test_get_web_toc_returns_payload_when_present(tmp_path):
    web_toc_json_path = _write_web_toc_fixture(tmp_path)
    client = _make_client(tmp_path, web_toc_json_path=web_toc_json_path)
    resp = client.get("/api/web-toc")
    assert resp.status_code == 200
    assert resp.json()["images"][0]["src"] == "bc-graphics/x"


def test_get_web_toc_returns_503_when_not_built(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/web-toc")
    assert resp.status_code == 503


def test_get_web_image_by_id_returns_cached_file(tmp_path):
    web_images_dir = tmp_path / "web_images"
    web_images_dir.mkdir()
    (web_images_dir / "fig1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
    web_toc_json_path = _write_web_toc_fixture(tmp_path, local_path="web_images/fig1.jpg")
    client = _make_client(tmp_path, web_toc_json_path=web_toc_json_path)

    resp = client.get("/api/web-image/fig1/thumbnail")

    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff\xe0fake"


def test_get_web_image_with_no_local_path_returns_404(tmp_path):
    web_toc_json_path = _write_web_toc_fixture(tmp_path, local_path="")
    client = _make_client(tmp_path, web_toc_json_path=web_toc_json_path)

    resp = client.get("/api/web-image/fig1/thumbnail")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "No cached image"


def test_get_web_image_unknown_id_returns_404(tmp_path):
    web_toc_json_path = _write_web_toc_fixture(tmp_path, local_path="web_images/fig1.jpg")
    client = _make_client(tmp_path, web_toc_json_path=web_toc_json_path)

    resp = client.get("/api/web-image/no-such-id/thumbnail")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "No cached image"


def test_get_web_image_missing_file_returns_404(tmp_path):
    web_toc_json_path = _write_web_toc_fixture(tmp_path, local_path="web_images/fig1.jpg")
    client = _make_client(tmp_path, web_toc_json_path=web_toc_json_path)

    resp = client.get("/api/web-image/fig1/thumbnail")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Cached image file missing"


def test_get_web_image_returns_503_when_web_toc_not_built(tmp_path):
    client = _make_client(tmp_path)

    resp = client.get("/api/web-image/fig1/thumbnail")

    assert resp.status_code == 503
