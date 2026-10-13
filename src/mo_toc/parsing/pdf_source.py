import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from shared.styled_text import StyledText, style_of


@dataclass(frozen=True)
class PageLine:
    bbox: tuple[float, float, float, float]
    text: str
    font: str
    # Bold/italic [start, end, style] ranges into `text` (see StyledText).
    emphasis: tuple[tuple[int, int, str], ...] = ()
    # Centred on its page - how a caption set in the plain body font is told
    # apart from a body-text reference (see classify_caption_line).
    centred: bool = False
    # (start, end, x0, x1) of each span's text in `text` - where on the line
    # it sits, so a line crossing narrow table columns can be split
    # (Table 3.2.3.1.-B's "1.2 1.5 2.0 ..." header). Empty when unknown.
    runs: tuple[tuple[int, int, float, float], ...] = ()

    @property
    def styled(self) -> StyledText:
        return StyledText(self.text, self.emphasis)

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]


@dataclass(frozen=True)
class PageImageInfo:
    bbox: tuple[float, float, float, float]
    xref: int
    # Whether the page draws the image mirrored left-right / upside down
    # relative to how it is stored (a negative scale in its transform).
    flipped_x: bool = False
    flipped_y: bool = False


@dataclass(frozen=True)
class ImageAlt:
    """An image placement's structure-tree /Alt text, and where the page draws it."""

    bbox: tuple[float, float, float, float]
    alt: str


@dataclass(frozen=True)
class ExtractedImage:
    data: bytes
    ext: str
    width: int
    height: int


class PdfSource(ABC):
    @property
    @abstractmethod
    def page_count(self) -> int: ...

    @abstractmethod
    def page_lines(self, page_index: int) -> list[PageLine]: ...

    @abstractmethod
    def page_images(self, page_index: int) -> list[PageImageInfo]: ...

    @abstractmethod
    def page_image_alts(self, page_index: int) -> list[ImageAlt]:
        """The /Alt text a tagged PDF's structure tree gives the page's image
        placements - none for an untagged or unreadable page, never an error."""

    @abstractmethod
    def extract_image(self, xref: int) -> ExtractedImage: ...

    @abstractmethod
    def page_drawing_rects(self, page_index: int) -> list[tuple[float, float, float, float]]: ...

    @abstractmethod
    def page_rule_rects(self, page_index: int) -> list[tuple[float, float, float, float]]:
        """The page's black or grey drawings - its table rules."""

    @abstractmethod
    def render_region(
        self, page_index: int, bbox: tuple[float, float, float, float]
    ) -> ExtractedImage: ...


# PyMuPDF span flags; the font name is checked too, since e.g. Arial-Black
# renders heavy without setting the bold flag.
_ITALIC_FLAG, _BOLD_FLAG = 2, 16
_BOLD_FONT_WORDS = ("Bold", "Black", "Heavy", "Semibold", "Demi")
_ITALIC_FONT_WORDS = ("Italic", "Oblique")
# Points a line's midpoint may sit off the page's to count as centred. Real
# centred captions sit ~4pt off; left-margin body lines ~185pt.
CENTRE_TOLERANCE = 20.0


def _span_style(span) -> str:
    font, flags = span["font"], span.get("flags", 0)
    bold = bool(flags & _BOLD_FLAG) or any(word in font for word in _BOLD_FONT_WORDS)
    italic = bool(flags & _ITALIC_FLAG) or any(word in font for word in _ITALIC_FONT_WORDS)
    return style_of(bold=bold, italic=italic)


# How far apart a drawing's RGB channels may be for it to count as black or
# grey. Table rules are black; the PDF's coloured strokes are the blue
# underlines under its cross-references (page 60's Table 1.3.1.2.), which a
# table's grid must not read as row rules.
_NEUTRAL_SPREAD = 0.05


def _is_neutral(drawing) -> bool:
    colour = drawing.get("fill") or drawing.get("color")
    return colour is None or max(colour) - min(colour) <= _NEUTRAL_SPREAD


def _line_font(spans) -> str:
    fonts = {s["font"] for s in spans}
    return fonts.pop() if len(fonts) == 1 else "/".join(sorted(fonts))


def _is_centred(bbox, page_width: float | None) -> bool:
    if page_width is None:
        return False
    return abs((bbox[0] + bbox[2]) / 2 - page_width / 2) <= CENTRE_TOLERANCE


def _span_runs(spans, text_length: int) -> tuple[tuple[int, int, float, float], ...]:
    """Each span's stretch of the line's text, which from_runs strips of
    the leading whitespace of the first span, and its x extent."""
    if not all("bbox" in span for span in spans):
        return ()
    runs, position = [], -(len(spans[0]["text"]) - len(spans[0]["text"].lstrip()))
    for span in spans:
        start, position = position, position + len(span["text"])
        runs.append((max(start, 0), min(position, text_length), span["bbox"][0], span["bbox"][2]))
    return tuple(runs)


def _line_from_span_dict(line_dict, page_width: float | None = None) -> PageLine | None:
    spans = [s for s in line_dict["spans"] if s["text"].strip()]
    if not spans:
        return None
    styled = StyledText.from_runs((s["text"], _span_style(s)) for s in spans)
    return PageLine(
        bbox=tuple(line_dict["bbox"]),
        text=styled.text,
        font=_line_font(spans),
        emphasis=styled.emphasis,
        centred=_is_centred(line_dict["bbox"], page_width),
        runs=_span_runs(spans, len(styled.text)),
    )


Matrix = tuple[float, float, float, float, float, float]
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# One content-stream token: a comment, a literal string (with one level of
# nested parentheses), a dictionary, a hex string, an inline image, a name, a
# number or an operator. Strings and inline images match whole, so the words
# and bytes inside them are never read as operators.
_CONTENT_TOKEN = re.compile(
    rb"%[^\r\n]*"
    rb"|\((?:[^()\\]|\\.|\((?:[^()\\]|\\.)*\))*\)"
    rb"|<<.*?>>"
    rb"|<[0-9A-Fa-f\s]*>"
    rb"|\bBI\b.*?\bEI\b"
    rb"|/[^\s/\[\]()<>{}%]*"
    rb"|[+-]?(?:\d+\.?\d*|\.\d+)"
    rb"|[A-Za-z'\"*][A-Za-z0-9*]*",
    re.S,
)
_OPERAND_START = b"/(<+-.0123456789"
_MCID = re.compile(rb"/MCID\s+(\d+)")


def _multiply(m: Matrix, n: Matrix) -> Matrix:
    """m then n, as PDF composes a `cm` operand m with the current transform n."""
    a, b, c, d, e, f = m
    na, nb, nc, nd, ne, nf = n
    return (
        a * na + b * nc,
        a * nb + b * nd,
        c * na + d * nc,
        c * nb + d * nd,
        e * na + f * nc + ne,
        e * nb + f * nd + nf,
    )


def _matrix(operands: list[bytes]) -> Matrix:
    if len(operands) < 6:
        raise ValueError("cm takes six operands")
    return tuple(float(x) for x in operands[-6:])


def _mcid(operands: list[bytes]) -> int | None:
    match = _MCID.search(operands[-1]) if operands else None
    return int(match.group(1)) if match else None


class _ContentReader:
    """Follows a content stream's graphics state (q/Q/cm) and marked content
    (BDC/BMC/EMC), recording each Do with its transform and innermost MCID."""

    def __init__(self) -> None:
        self.ctm: Matrix = _IDENTITY
        self.saved: list[Matrix] = []
        self.marked: list[int | None] = []
        self.operands: list[bytes] = []
        self.placements: list[tuple[Matrix, int | None]] = []

    def read(self, token: bytes) -> None:
        if token[:1] == b"%":
            return
        if token[:1] in _OPERAND_START:
            self.operands.append(token)
            return
        handler = _OPERATORS.get(token)
        if handler is not None:
            handler(self)
        self.operands = []

    def save(self) -> None:
        self.saved.append(self.ctm)

    def restore(self) -> None:
        if self.saved:
            self.ctm = self.saved.pop()

    def transform(self) -> None:
        self.ctm = _multiply(_matrix(self.operands), self.ctm)

    def begin_marked(self) -> None:
        self.marked.append(_mcid(self.operands))

    def end_marked(self) -> None:
        if self.marked:
            self.marked.pop()

    def draw(self) -> None:
        mcid = next((m for m in reversed(self.marked) if m is not None), None)
        self.placements.append((self.ctm, mcid))


_OPERATORS = {
    b"q": _ContentReader.save,
    b"Q": _ContentReader.restore,
    b"cm": _ContentReader.transform,
    b"BDC": _ContentReader.begin_marked,
    b"BMC": _ContentReader.begin_marked,
    b"EMC": _ContentReader.end_marked,
    b"Do": _ContentReader.draw,
}


def image_placements(content: bytes) -> list[tuple[Matrix, int | None]]:
    """Every XObject a content stream draws (`/Name Do`): the transform it is
    drawn with, in PDF space, and the marked-content id (MCID) around it."""
    reader = _ContentReader()
    for token in _CONTENT_TOKEN.findall(content):
        reader.read(token)
    return reader.placements


# A tagged PDF's /ParentTree is a number tree mapping a page's /StructParents
# number to an array whose MCID-th entry is the structure element that marked
# content belongs to - the element whose /Alt describes the image drawn there.
_NUMS_TOKEN = re.compile(r"\[[^\]]*\]|\d+\s+\d+\s+R|null|-?\d+")
_ARRAY_ITEM = re.compile(r"\d+\s+\d+\s+R|null")
_REF = re.compile(r"(\d+)\s+\d+\s+R")
_MAX_TREE_DEPTH = 16


def _nums_value(nums: str, key: int) -> str | None:
    tokens = _NUMS_TOKEN.findall(nums.strip()[1:-1])  # inside the /Nums array's own brackets
    for number, value in zip(tokens[0::2], tokens[1::2], strict=False):
        if number.lstrip("-").isdigit() and int(number) == key:
            return value
    return None


def _within_limits(limits: tuple[str, str], key: int) -> bool:
    kind, value = limits
    if kind != "array":
        return True
    bounds = [int(n) for n in re.findall(r"-?\d+", value)]
    return len(bounds) == 2 and bounds[0] <= key <= bounds[1]


def _array_items(array: str) -> list[int | None]:
    if not array.lstrip().startswith("["):
        return []
    return [None if item == "null" else int(item.split()[0]) for item in _ARRAY_ITEM.findall(array)]


def _ref(entry: tuple[str, str]) -> int | None:
    kind, value = entry
    return int(value.split()[0]) if kind == "xref" else None


def _placed_bbox(ctm: Matrix, page_matrix) -> tuple[float, float, float, float]:
    """Where an XObject drawn with `ctm` (its unit square) lands on the page."""
    import pymupdf as fitz

    return tuple(fitz.Rect(0, 0, 1, 1) * fitz.Matrix(*ctm) * page_matrix)


class PyMuPdfSource(PdfSource):
    def __init__(self, pdf_path: str):
        import pymupdf as fitz

        self._doc = fitz.open(pdf_path)

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def page_lines(self, page_index: int) -> list[PageLine]:
        page = self._doc[page_index]
        blocks = page.get_text("dict")["blocks"]
        raw_lines = [line for block in blocks for line in block.get("lines", [])]
        width = page.rect.width
        lines = [ln for ln in (_line_from_span_dict(rl, width) for rl in raw_lines) if ln]
        lines.sort(key=lambda ln: (ln.y0, ln.x0))
        return lines

    def page_images(self, page_index: int) -> list[PageImageInfo]:
        infos = self._doc[page_index].get_image_info(xrefs=True)
        return [
            PageImageInfo(
                bbox=tuple(i["bbox"]),
                xref=i["xref"],
                flipped_x=i["transform"][0] < 0,
                flipped_y=i["transform"][3] < 0,
            )
            for i in infos
        ]

    def page_image_alts(self, page_index: int) -> list[ImageAlt]:
        try:
            return self._page_image_alts(self._doc[page_index])
        except Exception:  # a malformed structure tree or content stream: no alts
            return []

    def _page_image_alts(self, page) -> list[ImageAlt]:
        elements = self._marked_content_elements(page)
        if not elements:
            return []
        alts = []
        for ctm, mcid in image_placements(page.read_contents()):
            alt = self._alt_of(elements, mcid)
            if alt is not None:
                alts.append(ImageAlt(_placed_bbox(ctm, page.transformation_matrix), alt))
        return alts

    def _key(self, xref: int | None, key: str) -> tuple[str, str]:
        return self._doc.xref_get_key(xref, key) if xref is not None else ("null", "null")

    def _marked_content_elements(self, page) -> list[int | None]:
        """The page's structure elements, indexed by MCID."""
        kind, number = self._key(page.xref, "StructParents")
        root = _ref(self._key(self._doc.pdf_catalog(), "StructTreeRoot"))
        tree = _ref(self._key(root, "ParentTree"))
        if kind != "int" or tree is None:
            return []
        value = self._number_tree_value(tree, int(number)) or ""
        array = _REF.fullmatch(value)
        return _array_items(self._doc.xref_object(int(array.group(1))) if array else value)

    def _number_tree_value(self, node: int | None, key: int) -> str | None:
        for _ in range(_MAX_TREE_DEPTH):
            if node is None:
                return None
            kind, nums = self._key(node, "Nums")
            if kind == "array":
                return _nums_value(nums, key)
            node = self._kid_holding(node, key)
        return None

    def _kid_holding(self, node: int, key: int) -> int | None:
        kind, kids = self._key(node, "Kids")
        if kind != "array":
            return None
        refs = [int(kid) for kid in _REF.findall(kids)]
        return next((kid for kid in refs if _within_limits(self._key(kid, "Limits"), key)), None)

    def _alt_of(self, elements: list[int | None], mcid: int | None) -> str | None:
        if mcid is None or mcid >= len(elements) or elements[mcid] is None:
            return None
        kind, alt = self._key(elements[mcid], "Alt")
        return alt if kind == "string" else None

    def extract_image(self, xref: int) -> ExtractedImage:
        info = self._doc.extract_image(xref)
        return ExtractedImage(
            data=info["image"], ext=info["ext"], width=info["width"], height=info["height"]
        )

    def page_drawing_rects(self, page_index: int) -> list[tuple[float, float, float, float]]:
        drawings = self._doc[page_index].get_drawings()
        return [tuple(d["rect"]) for d in drawings]

    def page_rule_rects(self, page_index: int) -> list[tuple[float, float, float, float]]:
        drawings = self._doc[page_index].get_drawings()
        return [tuple(d["rect"]) for d in drawings if _is_neutral(d)]

    def render_region(
        self, page_index: int, bbox: tuple[float, float, float, float]
    ) -> ExtractedImage:
        import pymupdf as fitz

        zoom = 3
        pixmap = self._doc[page_index].get_pixmap(
            clip=fitz.Rect(*bbox), matrix=fitz.Matrix(zoom, zoom)
        )
        return ExtractedImage(
            data=pixmap.tobytes("png"), ext="png", width=pixmap.width, height=pixmap.height
        )
