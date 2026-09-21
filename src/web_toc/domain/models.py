from dataclasses import dataclass, field


@dataclass
class WebNode:
    type: str
    identifier: str
    citation: str
    title: str
    path: str
    children: list["WebNode"] = field(default_factory=list)
    unified_number: str = ""


@dataclass
class WebImage:
    id: str
    src: str
    alt_text: str
    owner_citation: str
    local_path: str = ""
