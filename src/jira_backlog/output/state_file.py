"""The backlog item key -> JIRA issue key map of what has been created,
kept in a JSON file so a re-run never creates the same epic or story twice."""

import json
from pathlib import Path


class JsonStateStore(dict):
    def __init__(self, path: Path):
        self._path = path
        super().__init__(json.loads(path.read_text()) if path.exists() else {})

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(dict(self), indent=2) + "\n")
