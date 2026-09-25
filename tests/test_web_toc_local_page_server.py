import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

import pytest

from web_toc.parsing.local_page_server import QuietServer, serve_pages


@pytest.fixture
def pages_dir(tmp_path):
    (tmp_path / "nbc.divA.part1.html").write_text("<html>page</html>")
    (tmp_path / "assets" / "graphics").mkdir(parents=True)
    (tmp_path / "assets" / "graphics" / "a.jpg").write_bytes(b"jpg")
    (tmp_path / "secret.txt").write_text("no")
    return tmp_path


def _get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.headers["Content-Type"], response.read()


def _status(url):
    try:
        return _get(url)[0]
    except urllib.error.HTTPError as error:
        return error.code


def test_serves_saved_pages_at_the_root(pages_dir):
    with serve_pages(pages_dir) as base_url:
        status, content_type, body = _get(f"{base_url}/nbc.divA.part1.html")
    assert (status, body) == (200, b"<html>page</html>")
    assert content_type.startswith("text/html")


def test_serves_mirrored_assets_under_the_web_assets_prefix(pages_dir):
    with serve_pages(pages_dir) as base_url:
        status, content_type, body = _get(f"{base_url}/web-assets/graphics/a.jpg")
    assert (status, content_type, body) == (200, "image/jpeg", b"jpg")


@pytest.mark.parametrize(
    "path",
    [
        "/missing.html",
        "/secret.txt",
        "/web-assets/graphics/missing.jpg",
        "/web-assets/../nbc.divA.part1.html",
        "/web-assets/",
        "/",
    ],
)
def test_answers_404_for_anything_else(pages_dir, path):
    with serve_pages(pages_dir) as base_url:
        assert _status(f"{base_url}{path}") == 404


def test_a_client_dropping_its_connection_is_not_reported(capsys):
    # The browser abandons requests it no longer needs (e.g. lazy images).
    server = QuietServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        try:
            raise BrokenPipeError(32, "Broken pipe")
        except BrokenPipeError:
            server.handle_error(None, ("127.0.0.1", 1))
    finally:
        server.server_close()
    assert capsys.readouterr().err == ""


def test_other_request_errors_are_still_reported(capsys):
    server = QuietServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            server.handle_error(None, ("127.0.0.1", 1))
    finally:
        server.server_close()
    assert "ValueError: boom" in capsys.readouterr().err


def test_stops_serving_once_the_block_exits(pages_dir):
    with serve_pages(pages_dir) as base_url:
        pass
    with pytest.raises(urllib.error.URLError):
        _get(f"{base_url}/nbc.divA.part1.html")
