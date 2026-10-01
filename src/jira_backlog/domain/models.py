"""Plain records for the AOT Pulse backlog - what is read from the source
documents and what becomes a JIRA epic or story. No I/O, no JIRA specifics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EpicTableRow:
    """One row of an epic's user-story table in the epics document."""

    number: int
    story: str
    criteria: str
    status: str


@dataclass(frozen=True)
class ParsedEpic:
    number: int
    title: str
    note: str | None
    rows: tuple[EpicTableRow, ...]


@dataclass(frozen=True)
class SpecStory:
    """A "### User Story N - ..." block of a spec-kit spec.md."""

    number: int
    title: str
    priority: str | None
    narrative: str
    why: str | None
    independent_test: str | None
    acceptance: tuple[str, ...]


@dataclass(frozen=True)
class SpecFeature:
    folder: str
    title: str
    status: str | None
    summary: str | None
    stories: tuple[SpecStory, ...]


@dataclass(frozen=True)
class Section:
    """A titled block of a description: a paragraph, or a list when ``items``."""

    heading: str
    text: str = ""
    items: tuple[str, ...] = ()
    ordered: bool = False


@dataclass(frozen=True)
class BacklogStory:
    """A story ready to publish; ``key`` is stable across runs (resume/dedupe)."""

    key: str
    summary: str
    sections: tuple[Section, ...]
    labels: tuple[str, ...] = ()
    priority: str | None = None


@dataclass(frozen=True)
class BacklogEpic:
    key: str
    summary: str
    sections: tuple[Section, ...]
    stories: tuple[BacklogStory, ...]
    labels: tuple[str, ...] = ()
