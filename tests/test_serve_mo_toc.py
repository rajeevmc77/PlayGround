import pytest
from fastapi.testclient import TestClient

import serve_mo_toc
from serve_mo_toc import app


def test_app_serves_index_page():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"MO Package TOC Viewer" in resp.content


def test_main_exits_when_toc_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(serve_mo_toc, "TOC_JSON", str(tmp_path / "missing.json"))

    with pytest.raises(SystemExit) as exc_info:
        serve_mo_toc.main()

    assert "No such file" in str(exc_info.value)
