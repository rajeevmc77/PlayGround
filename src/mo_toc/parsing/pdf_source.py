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
        return [PageImageInfo(bbox=tuple(i["bbox"]), xref=i["xref"]) for i in infos]

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
