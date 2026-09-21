import dataclasses
import json
from pathlib import Path

from mo_toc.domain.models import Caption, ImageAsset, Node

_CONTENT_TYPES = {"Sentence", "Clause", "Subclause", "Cell"}
_NO_TITLE_TYPES = _CONTENT_TYPES | {"Row"}


def _prune_node(node_dict: dict) -> dict:
    if node_dict["type"] not in _CONTENT_TYPES:
        node_dict.pop("content", None)
    if node_dict["type"] in _NO_TITLE_TYPES:
        node_dict.pop("title", None)
    node_dict["children"] = [_prune_node(child) for child in node_dict["children"]]
    return node_dict


def write_json(
    volume: Node, captions: list[Caption], images: list[ImageAsset], out_path: str
) -> None:
    payload = {
        "volume": _prune_node(dataclasses.asdict(volume)),
        "captions": [dataclasses.asdict(c) for c in captions],
        "images": [dataclasses.asdict(i) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
