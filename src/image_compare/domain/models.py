from dataclasses import dataclass, field


@dataclass
class MatchedStem:
    stem: str
    pdf_filename: str
    web_filename: str


@dataclass
class PairingResult:
    matched: list[MatchedStem] = field(default_factory=list)
    pdf_only: list[str] = field(default_factory=list)
    web_only: list[str] = field(default_factory=list)


@dataclass
class ComparisonResult:
    stem: str
    hash_distance: int
    similarity_percent: float
