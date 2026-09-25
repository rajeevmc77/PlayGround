"""Reads the navigation tree and content JSON that build_web_pages.py cached
under output/web_source/ - the offline stand-in for the live site."""

import json
from pathlib import Path

from web_toc.output.source_cache import NAVIGATION_FILE, content_file


class LocalWebSource:
    def __init__(self, source_dir: Path):
        self._source_dir = Path(source_dir)

    def fetch_navigation_tree(self) -> dict:
        path = self._source_dir / NAVIGATION_FILE
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run src/build_web_pages.py first")
        return json.loads(path.read_text(encoding="utf-8"))

    def fetch_content(self, citation: str) -> dict | None:
        path = content_file(self._source_dir, citation)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
