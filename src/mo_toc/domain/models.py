from dataclasses import dataclass, field


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class Node:
    type: str
    identifier: str
    citation: str
    title: str
    page: int
    end_page: int
    bbox: BBox
    children: list["Node"] = field(default_factory=list)
    unified_number: str = ""


@dataclass
class Caption:
    kind: str
    identifier: str
    title: str
    page: int
    bbox: BBox
    owner_citation: str
    forming_part_of: str | None
    continuation: bool


@dataclass
class ImageAsset:
    page: int
    bbox: BBox
    width: int
    height: int
    phash: str | None
    thumbnail_path: str
    owner_citation: str = ""
    caption_kind: str | None = None
    caption_identifier: str | None = None
    caption_title: str | None = None
