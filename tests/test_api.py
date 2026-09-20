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
                "thumbnail_path": "thumbnails/img_0.png",
            }
        ],
    }
    path = tmp_path / "mo_toc.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _make_client(tmp_path, pdf_path=None, create_thumbnail=True, web_toc_json_path=None):
    json_path = _write_fixture_json(tmp_path)
    thumbs_dir = tmp_path / "thumbnails"
    thumbs_dir.mkdir()
    if create_thumbnail:
        (thumbs_dir / "img_0.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    if pdf_path is None:
        pdf_path = tmp_path / "sample.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
    app = create_app(
        toc_json_path=json_path,
        pdf_path=str(pdf_path),
        thumbnails_dir=str(thumbs_dir),
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


def test_get_thumbnail_by_index(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/image/0/thumbnail")
    assert resp.status_code == 200


def test_get_thumbnail_out_of_range_returns_404(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/image/99/thumbnail")
    assert resp.status_code == 404


def test_get_thumbnail_missing_file_returns_404(tmp_path):
    client = _make_client(tmp_path, create_thumbnail=False)
    resp = client.get("/api/image/0/thumbnail")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Thumbnail file missing"


def _write_web_toc_fixture(tmp_path):
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
            {"id": "fig1", "src": "bc-graphics/x", "alt_text": "alt", "owner_citation": "root"}
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
