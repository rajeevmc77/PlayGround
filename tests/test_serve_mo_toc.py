import json

import pytest
from fastapi.testclient import TestClient

import serve_mo_toc
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
        "images": [],
    }
    path = tmp_path / "mo_pdf.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _make_client(tmp_path):
    json_path = _write_fixture_json(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    app = create_app(
        toc_json_path=json_path,
        pdf_path=str(pdf_path),
        images_dir=str(images_dir),
    )
    return TestClient(app)


def test_app_serves_index_page(tmp_path):
    # Built from a local fixture via create_app, not the real module-level
    # `serve_mo_toc.app` - that object reads the real output/mo_pdf.json,
    # a generated file .gitignore excludes, which wouldn't exist yet on a
    # fresh checkout and would break test collection.
    client = _make_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"MO Package TOC Viewer" in resp.content


def test_index_page_has_the_image_comparison_tab_and_its_panel(tmp_path):
    html = _make_client(tmp_path).get("/").text

    assert 'id="tab-llm-compare"' in html
    assert ">Image Comparison</button>" in html
    for element_id in (
        "llm-compare",
        "llm-message",
        "llm-cards",
        "llm-verdict",
        "llm-query",
        "llm-table",
    ):
        assert f'id="{element_id}"' in html
    assert html.index('id="tab-compare"') < html.index('id="tab-llm-compare"')


def test_main_exits_when_toc_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(serve_mo_toc, "TOC_JSON", str(tmp_path / "missing.json"))

    with pytest.raises(SystemExit) as exc_info:
        serve_mo_toc.main()

    assert "No such file" in str(exc_info.value)


def test_get_app_returns_503_for_web_toc_when_web_toc_json_missing(tmp_path, monkeypatch):
    toc_json_path = _write_fixture_json(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(serve_mo_toc, "TOC_JSON", toc_json_path)
    monkeypatch.setattr(serve_mo_toc, "PDF_PATH", str(pdf_path))
    monkeypatch.setattr(serve_mo_toc, "IMAGES_DIR", str(images_dir))
    monkeypatch.setattr(serve_mo_toc, "WEB_TOC_JSON", str(tmp_path / "missing_web_toc.json"))
    monkeypatch.setattr(serve_mo_toc, "_app", None)

    client = TestClient(serve_mo_toc._get_app())
    resp = client.get("/api/web-toc")
    assert resp.status_code == 503


def test_get_comparison_returns_503_when_comparison_json_missing(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/comparison")
    assert resp.status_code == 503


def test_get_comparison_returns_the_comparison_json_payload(tmp_path):
    json_path = _write_fixture_json(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(json.dumps({"threshold_percent": 80.0, "statuses": {"V.P1": True}}))

    app = create_app(
        toc_json_path=json_path,
        pdf_path=str(pdf_path),
        images_dir=str(images_dir),
        comparison_json_path=str(comparison_path),
    )
    resp = TestClient(app).get("/api/comparison")

    assert resp.status_code == 200
    assert resp.json() == {"threshold_percent": 80.0, "statuses": {"V.P1": True}}


def test_get_app_serves_scraped_web_pages_from_web_pages_dir(tmp_path, monkeypatch):
    toc_json_path = _write_fixture_json(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    pages_dir = tmp_path / "web_pages"
    pages_dir.mkdir()
    (pages_dir / "pages.json").write_text('{"nbc.divA.part1": "Part 1"}')
    (pages_dir / "nbc.divA.part1.html").write_text("<html>Part 1</html>")

    monkeypatch.setattr(serve_mo_toc, "TOC_JSON", toc_json_path)
    monkeypatch.setattr(serve_mo_toc, "PDF_PATH", str(pdf_path))
    monkeypatch.setattr(serve_mo_toc, "IMAGES_DIR", str(images_dir))
    monkeypatch.setattr(serve_mo_toc, "WEB_TOC_JSON", str(tmp_path / "missing_web_toc.json"))
    monkeypatch.setattr(serve_mo_toc, "WEB_PAGES_DIR", str(pages_dir))
    monkeypatch.setattr(serve_mo_toc, "_app", None)

    client = TestClient(serve_mo_toc._get_app())
    assert client.get("/web-page/nbc.divA.part1").text == "<html>Part 1</html>"


def test_get_app_wires_the_llm_report_and_images_from_the_output_dir(tmp_path, monkeypatch):
    toc_json_path = _write_fixture_json(tmp_path)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    report = output_dir / "llm_image_compare.json"

    monkeypatch.setattr(serve_mo_toc, "TOC_JSON", toc_json_path)
    monkeypatch.setattr(serve_mo_toc, "PDF_PATH", str(pdf_path))
    monkeypatch.setattr(serve_mo_toc, "IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(serve_mo_toc, "LLM_REPORT_JSON", str(report))
    monkeypatch.setattr(serve_mo_toc, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(serve_mo_toc, "_app", None)
    client = TestClient(serve_mo_toc._get_app())

    # The report does not exist yet: read lazily, so it still appears later.
    assert client.get("/api/llm-comparison").status_code == 503
    report.write_text(json.dumps({"rows": []}))
    assert client.get("/api/llm-comparison").json() == {"rows": []}
    assert client.get("/api/llm-image/pic.png").status_code == 200


def test_llm_paths_point_at_the_projects_output_dir():
    output = serve_mo_toc.PROJECT_ROOT / "output"
    assert serve_mo_toc.LLM_REPORT_JSON == str(output / "llm_image_compare.json")
    assert serve_mo_toc.OUTPUT_DIR == str(output)
