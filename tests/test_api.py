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
    path = tmp_path / "mo_pdf.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _make_client(
    tmp_path, pdf_path=None, create_image=True, web_toc_json_path=None, web_pages_dir=None
):
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
        web_pages_dir=web_pages_dir,
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


def test_create_app_works_with_a_file_literally_named_mo_pdf_json(tmp_path):
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
        "images": [],
    }
    toc_path = tmp_path / "mo_pdf.json"
    toc_path.write_text(json.dumps(payload))
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    app = create_app(
        toc_json_path=str(toc_path),
        pdf_path=str(pdf_path),
        images_dir=str(images_dir),
    )
    client = TestClient(app)
    response = client.get("/api/toc")
    assert response.json()["type"] == "Volume"


def _write_web_pages_fixture(tmp_path):
    pages_dir = tmp_path / "web_pages"
    (pages_dir / "assets" / "_next" / "static" / "chunks").mkdir(parents=True)
    (pages_dir / "nbc.divA.part1.sect1.html").write_text("<html>1.1. General</html>")
    (pages_dir / "pages.json").write_text('{"nbc.divA.part1.sect1": "Section 1"}')
    (pages_dir / "assets" / "_next" / "static" / "chunks" / "a.css").write_text(".x{}")
    (pages_dir / "assets" / "site-nav.css").write_text(".nav-tree{}")
    (tmp_path / "secret.txt").write_text("outside")
    return str(pages_dir)


def test_web_page_returns_503_when_not_built(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=str(tmp_path / "missing"))
    assert client.get("/web-page/nbc.divA.part1.sect1").status_code == 503


def test_get_web_page_serves_the_scraped_html(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    resp = client.get("/web-page/nbc.divA.part1.sect1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "1.1. General" in resp.text


def test_get_web_page_unknown_citation_returns_404(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    assert client.get("/web-page/nbc.divZ").status_code == 404


def test_get_web_page_rejects_an_unsafe_citation(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    assert client.get("/web-page/..%2Fsecret").status_code == 404


def test_get_web_page_returns_503_when_no_dir_configured(tmp_path):
    assert _make_client(tmp_path).get("/web-page/nbc.divA.part1.sect1").status_code == 503


def test_get_web_asset_serves_a_mirrored_file(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    resp = client.get("/web-assets/_next/static/chunks/a.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert resp.text == ".x{}"


def test_get_web_asset_serves_the_site_nav_stylesheet(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    assert client.get("/web-assets/site-nav.css").text == ".nav-tree{}"


def test_get_web_asset_missing_file_returns_404(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    assert client.get("/web-assets/graphics/none.jpg").status_code == 404


def test_get_web_asset_refuses_to_escape_the_assets_dir(tmp_path):
    client = _make_client(tmp_path, web_pages_dir=_write_web_pages_fixture(tmp_path))
    assert client.get("/web-assets/..%2F..%2Fsecret.txt").status_code == 404


def test_get_web_asset_returns_503_when_no_dir_configured(tmp_path):
    assert _make_client(tmp_path).get("/web-assets/site-nav.css").status_code == 503
