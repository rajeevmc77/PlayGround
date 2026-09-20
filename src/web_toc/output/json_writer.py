import dataclasses
import json
from pathlib import Path

from web_toc.domain.models import WebImage, WebNode


def write_json(root: WebNode, images: list[WebImage], out_path: str) -> None:
    payload = {
        "tree": dataclasses.asdict(root),
        "images": [dataclasses.asdict(i) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
