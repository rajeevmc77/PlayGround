import dataclasses
import json
from pathlib import Path

from web_toc.domain.models import WebImage, WebNode


def _drop_empty_headings(node_dict: dict) -> dict:
    if not node_dict.get("heading"):
        node_dict.pop("heading", None)
    node_dict["children"] = [_drop_empty_headings(child) for child in node_dict["children"]]
    return node_dict


def write_json(root: WebNode, images: list[WebImage], out_path: str) -> None:
    payload = {
        "tree": _drop_empty_headings(dataclasses.asdict(root)),
        "images": [dataclasses.asdict(i) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
