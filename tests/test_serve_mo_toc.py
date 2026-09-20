from fastapi.testclient import TestClient

from serve_mo_toc import app


def test_app_serves_index_page():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"MO Package TOC Viewer" in resp.content
