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
    # Bold/italic [start, end, style] ranges into `content`, as rendered
    # (see shared/styled_text.py). Set by layout_join with the text.
    emphasis: list[list] = field(default_factory=list)
    # {"page_file", "xpath", "bbox"} into a locally scraped page - the web
    # counterpart of the PDF's page + bbox. None until layout_join finds it.
    location: dict | None = None


@dataclass
class WebImage:
    id: str
    src: str
    alt_text: str
    owner_citation: str
    local_path: str = ""
    unified_number: str = ""
    location: dict | None = None
    # "figure" (a graphic from the content JSON) or "equation" (a rendered
    # formula captured from the saved page as a PNG).
    kind: str = "figure"


@dataclass
class EquationCapture:
    """A saved page with each MathJax-rendered equation swapped for an <img>
    of itself, plus those images as PNG bytes keyed by equation key."""

    html: str
    images: dict[str, bytes]


@dataclass
class ScrapedPage:
    """One live-site reading page as rendered in a real browser: the
    `main.ui-ContentPanel` markup plus the styling it was rendered with.
    `incomplete` maps a table id to [rendered rows, expected rows] for every
    table the site never finished lazy-loading."""

    panel: str
    title: str
    stylesheets: list[str] = field(default_factory=list)
    inline_styles: list[str] = field(default_factory=list)
    incomplete: dict[str, list[int]] = field(default_factory=dict)
