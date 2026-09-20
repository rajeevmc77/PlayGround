import dataclasses
import json
from pathlib import Path

from mo_toc.domain.models import Caption, ImageAsset, Node


def write_json(
    volume: Node, captions: list[Caption], images: list[ImageAsset], out_path: str
) -> None:
    payload = {
        "volume": dataclasses.asdict(volume),
        "captions": [dataclasses.asdict(c) for c in captions],
        "images": [dataclasses.asdict(i) for i in images],
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
