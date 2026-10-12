"""Plain data the LLM image comparison passes between its steps."""

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    MATCH_PHASH = "MATCH_PHASH"
    IDENTICAL = "IDENTICAL"
    DIFFERENT = "DIFFERENT"
    SKIPPED = "SKIPPED"
    WEB_ONLY = "WEB_ONLY"
    ERROR = "ERROR"


class Route(StrEnum):
    MATCH_PHASH = "MATCH_PHASH"
    TO_LLM = "TO_LLM"


LLM_VERDICTS = (Verdict.IDENTICAL, Verdict.DIFFERENT)


@dataclass(frozen=True)
class PdfLocation:
    """Where an image sits in the PDF: its 1-based page and box in points (origin top-left)."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class WebLocation:
    """Where an image sits in a saved web page: the page file (relative to the source
    directory), its xpath, its box in CSS px from the content panel's top-left, and the
    image's element id (used to find the nearest anchor in the page)."""

    page_file: str
    xpath: str
    x0: float
    y0: float
    x1: float
    y1: float
    element_id: str


@dataclass(frozen=True)
class ImagePair:
    """One report row's inputs. `pdf_path`/`web_path` are relative to the source directory;
    a missing side is None. `skip_reason` is set when the row cannot be compared."""

    row_id: str
    key: str
    pdf_path: str | None
    web_path: str | None
    web_key: str | None = None
    skip_reason: str = ""
    pdf_location: PdfLocation | None = None
    web_location: WebLocation | None = None


@dataclass(frozen=True)
class PreparedImage:
    png: bytes
    width: int
    height: int
    source_width: int
    source_height: int


@dataclass(frozen=True)
class PreparedPair:
    pair: ImagePair
    score: float
    pdf: PreparedImage
    web: PreparedImage
    tokens: int

    @property
    def row_id(self) -> str:
        return self.pair.row_id

    @property
    def key(self) -> str:
        return self.pair.key


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = 0.0


@dataclass(frozen=True)
class Prices:
    input_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class PairVerdict:
    pair_id: int
    verdict: Verdict
    differences: tuple[str, ...] = ()


@dataclass(frozen=True)
class PairRecord:
    row_id: str
    key: str
    verdict: Verdict
    pdf_path: str | None
    web_path: str | None
    web_key: str | None = None
    score: float | None = None
    differences: tuple[str, ...] = ()
    message: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    batch_id: int | None = None
    cached: bool = False
    sent_pdf: tuple[int, int] | None = None
    sent_web: tuple[int, int] | None = None
    # How long the model took to answer the call that gave this verdict (a batch's pairs
    # share their call's figure); None for a row that did not come from a call of this run.
    call_seconds: float | None = None
    pdf_location: PdfLocation | None = None
    web_location: WebLocation | None = None
