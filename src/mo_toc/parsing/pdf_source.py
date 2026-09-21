from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PageLine:
    bbox: tuple[float, float, float, float]
    text: str
    font: str

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
    def render_region(
        self, page_index: int, bbox: tuple[float, float, float, float]
    ) -> ExtractedImage: ...


def _line_from_span_dict(line_dict) -> PageLine | None:
    spans = [s for s in line_dict["spans"] if s["text"].strip()]
    if not spans:
        return None
    text = "".join(s["text"] for s in spans).strip()
    if not text:
        return None
    fonts = {s["font"] for s in spans}
    font = fonts.pop() if len(fonts) == 1 else "/".join(sorted(fonts))
    return PageLine(bbox=tuple(line_dict["bbox"]), text=text, font=font)


class PyMuPdfSource(PdfSource):
    def __init__(self, pdf_path: str):
        import pymupdf as fitz

        self._doc = fitz.open(pdf_path)

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def page_lines(self, page_index: int) -> list[PageLine]:
        blocks = self._doc[page_index].get_text("dict")["blocks"]
        raw_lines = [line for block in blocks for line in block.get("lines", [])]
        lines = [ln for ln in (_line_from_span_dict(rl) for rl in raw_lines) if ln]
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
