from dataclasses import dataclass, field


@dataclass
class Equation:
    id: str
    latex: str


@dataclass
class ExportResult:
    written: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
