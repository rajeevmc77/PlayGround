from typing import Protocol

import httpx


class WebSource(Protocol):
    def fetch_navigation_tree(self) -> dict: ...
    def fetch_content(self, path: str) -> dict | None: ...


class HttpxWebSource:
    def __init__(self, base_url: str, version: str):
        self._base_url = base_url.rstrip("/")
        self._version = version

    def fetch_navigation_tree(self) -> dict:
        url = f"{self._base_url}/data/{self._version}/navigation-tree.json"
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        return response.json()

    def fetch_content(self, path: str) -> dict | None:
        url = f"{self._base_url}{path}"
        response = httpx.get(url, timeout=30.0)
        if not response.text.strip().startswith("{"):
            return None
        return response.json()
