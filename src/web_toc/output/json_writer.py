import dataclasses
import json
from pathlib import Path

from web_toc.domain.models import WebImage, WebNode


def _drop_unset(node_dict: dict) -> dict:
    """Omits keys with nothing in them: an empty heading, a missing location."""
    if not node_dict.get("heading"):
        node_dict.pop("heading", None)
    if node_dict.get("location") is None:
        node_dict.pop("location", None)
    return node_dict


def _node_dict(node_dict: dict) -> dict:
    node_dict["children"] = [_node_dict(child) for child in node_dict["children"]]
    return _drop_unset(node_dict)


def write_json(root: WebNode, images: list[WebImage], out_path: str) -> None:
    payload = {
        "tree": _node_dict(dataclasses.asdict(root)),
        "images": [_drop_unset(dataclasses.asdict(i)) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
