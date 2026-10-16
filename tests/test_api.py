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


def _make_llm_client(tmp_path, **kwargs):
    json_path = _write_fixture_json(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir(exist_ok=True)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    app = create_app(
        toc_json_path=json_path, pdf_path=str(pdf_path), images_dir=str(images_dir), **kwargs
    )
    return TestClient(app)


def test_llm_comparison_returns_the_report(tmp_path):
    report = tmp_path / "llm_image_compare.json"
    report.write_text(json.dumps({"summary": {"total_rows": 1}, "rows": []}))
    client = _make_llm_client(tmp_path, llm_report_path=str(report))

    resp = client.get("/api/llm-comparison")

    assert resp.status_code == 200
    assert resp.json() == {"summary": {"total_rows": 1}, "rows": []}


def test_llm_comparison_rereads_the_file_on_every_request(tmp_path):
    report = tmp_path / "llm_image_compare.json"
    client = _make_llm_client(tmp_path, llm_report_path=str(report))
    assert client.get("/api/llm-comparison").status_code == 503

    report.write_text(json.dumps({"rows": [1]}))
    assert client.get("/api/llm-comparison").json() == {"rows": [1]}

    report.write_text(json.dumps({"rows": [1, 2]}))
    assert client.get("/api/llm-comparison").json() == {"rows": [1, 2]}


def test_llm_comparison_returns_503_when_the_path_is_unset(tmp_path):
    resp = _make_llm_client(tmp_path).get("/api/llm-comparison")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Run src/build_llm_comparison.py first"


def test_llm_comparison_returns_503_when_the_file_is_missing(tmp_path):
    client = _make_llm_client(tmp_path, llm_report_path=str(tmp_path / "nope.json"))

    resp = client.get("/api/llm-comparison")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Run src/build_llm_comparison.py first"


def test_llm_comparison_returns_503_for_a_file_that_is_not_json(tmp_path):
    report = tmp_path / "llm_image_compare.json"
    report.write_text('{"rows": [')
    client = _make_llm_client(tmp_path, llm_report_path=str(report))

    resp = client.get("/api/llm-comparison")

    assert resp.status_code == 503
    assert "not valid JSON" in resp.json()["detail"]
    assert "build_llm_comparison.py" in resp.json()["detail"]


def _llm_output_dir(tmp_path):
    out = tmp_path / "output"
    (out / "images").mkdir(parents=True)
    (out / "images" / "a b.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return out


def test_llm_image_serves_a_file_under_the_output_dir(tmp_path):
    out = _llm_output_dir(tmp_path)
    client = _make_llm_client(tmp_path, output_dir=str(out))

    resp = client.get("/api/llm-image/images/a%20b.png")

    assert resp.status_code == 200
    assert resp.content.endswith(b"fake")


def test_llm_image_returns_404_for_a_missing_file(tmp_path):
    client = _make_llm_client(tmp_path, output_dir=str(_llm_output_dir(tmp_path)))

    assert client.get("/api/llm-image/images/none.png").status_code == 404


def test_llm_image_returns_404_for_a_directory(tmp_path):
    client = _make_llm_client(tmp_path, output_dir=str(_llm_output_dir(tmp_path)))

    assert client.get("/api/llm-image/images").status_code == 404


def test_llm_image_refuses_dot_dot_traversal(tmp_path):
    out = _llm_output_dir(tmp_path)
    (tmp_path / "secret.txt").write_text("secret")
    client = _make_llm_client(tmp_path, output_dir=str(out))

    for url in ("/api/llm-image/../secret.txt", "/api/llm-image/images/%2e%2e/%2e%2e/secret.txt"):
        assert client.get(url).status_code == 404
    assert client.get("/api/llm-image/images%2F..%2F..%2Fsecret.txt").status_code == 404


def test_llm_image_returns_404_for_a_nul_byte_in_the_path(tmp_path):
    client = _make_llm_client(tmp_path, output_dir=str(_llm_output_dir(tmp_path)))

    assert client.get("/api/llm-image/images/a%00.png").status_code == 404


def test_llm_image_refuses_an_absolute_path(tmp_path):
    out = _llm_output_dir(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    client = _make_llm_client(tmp_path, output_dir=str(out))

    assert client.get(f"/api/llm-image/{outside}").status_code == 404
    assert client.get(f"/api/llm-image/%2F{str(outside).lstrip('/')}").status_code == 404


def test_llm_image_refuses_a_symlink_that_escapes_the_output_dir(tmp_path):
    out = _llm_output_dir(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (out / "images" / "link.png").symlink_to(outside)
    client = _make_llm_client(tmp_path, output_dir=str(out))

    assert client.get("/api/llm-image/images/link.png").status_code == 404


def test_llm_image_returns_503_when_no_output_dir_is_configured(tmp_path):
    assert _make_llm_client(tmp_path).get("/api/llm-image/images/a.png").status_code == 503
