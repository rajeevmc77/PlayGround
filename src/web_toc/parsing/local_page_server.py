"""Serves output/web_pages/ over HTTP on localhost, laid out the way the
viewer serves it - pages at `/<citation>.html`, the asset mirror under
`/web-assets/` - so a headless browser renders each saved page with the same
stylesheets and fonts it will have in the viewer."""

import mimetypes
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from web_toc.output.page_writer import asset_file, page_file
from web_toc.parsing.page_html import ASSET_PREFIX


def resolve_request(pages_dir: Path, request_path: str) -> Path | None:
    path = unquote(urlsplit(request_path).path)
    if path.startswith(f"{ASSET_PREFIX}/"):
        target = asset_file(pages_dir / "assets", path[len(ASSET_PREFIX) :])
    elif path.endswith(".html"):
        target = page_file(pages_dir, path[1:-5])
    else:
        target = None
    return target if target is not None and target.is_file() else None


class _PageHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, pages_dir: Path, **kwargs):
        self._pages_dir = pages_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        target = resolve_request(self._pages_dir, self.path)
        if target is None:
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        """Silenced - one line per asset request would bury the build's own output."""


@contextmanager
def serve_pages(pages_dir: Path) -> Iterator[str]:
    """Yields the base URL of a server on an ephemeral localhost port."""
    handler = partial(_PageHandler, pages_dir=Path(pages_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
