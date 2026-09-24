from types import TracebackType
from typing import Protocol

import httpx


class WebSource(Protocol):
    async def fetch_navigation_tree(self) -> dict: ...
    async def fetch_content(self, path: str) -> dict | None: ...
    async def fetch_image(self, src: str) -> bytes | None: ...
    async def fetch_bytes(self, path: str) -> bytes | None: ...


class HttpxWebSource:
    """Owns one shared httpx.AsyncClient for the lifetime of an `async with`
    block, so concurrent fetches reuse pooled connections instead of each
    paying its own connection-setup cost."""

    def __init__(self, base_url: str, version: str):
        self._base_url = base_url.rstrip("/")
        self._version = version
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HttpxWebSource":
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        assert self._client is not None
        await self._client.aclose()
        self._client = None

    async def fetch_navigation_tree(self) -> dict:
        url = f"{self._base_url}/data/{self._version}/navigation-tree.json"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()

    async def fetch_content(self, path: str) -> dict | None:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.get(url)
        except httpx.HTTPError:
            return None
        if not response.text.strip().startswith("{"):
            return None
        return response.json()

    async def fetch_image(self, src: str) -> bytes | None:
        return await self.fetch_bytes(f"/{src}.jpg")

    async def fetch_bytes(self, path: str) -> bytes | None:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        return response.content
