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
    content: str = ""
    heading: str = ""


@dataclass
class WebImage:
    id: str
    src: str
    alt_text: str
    owner_citation: str
    local_path: str = ""
    unified_number: str = ""


@dataclass
class ScrapedPage:
    """One live-site reading page as rendered in a real browser: the
    `main.ui-ContentPanel` markup plus the styling it was rendered with."""

    panel: str
    title: str
    stylesheets: list[str] = field(default_factory=list)
    inline_styles: list[str] = field(default_factory=list)
