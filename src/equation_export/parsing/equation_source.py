from types import TracebackType

import httpx

from equation_export.domain.models import Equation


class HttpxEquationSource:
    """Owns one shared httpx.AsyncClient for the lifetime of an `async with`
    block, matching HttpxWebSource's connection-pooling rationale."""

    def __init__(self, base_url: str, version: str):
        self._base_url = base_url.rstrip("/")
        self._version = version
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HttpxEquationSource":
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

    async def fetch_equations(self) -> list[Equation]:
        url = f"{self._base_url}/data/{self._version}/equation-map.json"
        response = await self._client.get(url)
        response.raise_for_status()
        equation_map = response.json()
        return [
            Equation(id=entry["id"], latex=_normalize_latex(entry["latex"]))
            for entry in equation_map.values()
            if "latex" in entry
        ]


def _normalize_latex(latex: str) -> str:
    """The site's own equation-map.json double-escapes some LaTeX commands
    (e.g. two literal backslashes before `times`/`leq`), confirmed by
    comparing against the same entry's plainText field. Collapse them back
    to the single backslash mathtext/MathJax expect."""
    return latex.replace("\\\\", "\\")
