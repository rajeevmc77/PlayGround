"""Verdicts remembered by content, so a re-run or an interrupted run re-spends nothing."""

import hashlib
import json
from pathlib import Path

from llm_compare.domain.models import PreparedPair


def cache_key(pdf_png: bytes, web_png: bytes, prompt_version: str, model: str) -> str:
    digest = hashlib.sha256()
    for part in (pdf_png, web_png, prompt_version.encode(), model.encode()):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def pair_cache_key(pair: PreparedPair, prompt_version: str, model: str) -> str:
    return cache_key(pair.pdf.png, pair.web.png, prompt_version, model)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class VerdictCache:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._entries: dict[str, dict] = _read(path) if path is not None else {}

    def get(self, key: str) -> dict | None:
        return self._entries.get(key)

    def put(self, key: str, entry: dict) -> None:
        self._entries[key] = entry

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._entries))
        temporary.replace(self._path)
