"""Joins the epics document with the spec-kit specs into publishable epics and
stories. Each epic's own table rows become stories; an epic may also describe
the spec it formalizes (``context``) and take on the stories of specs the
epics document never listed (``extra_stories``)."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from jira_backlog.domain.models import (
    BacklogEpic,
    BacklogStory,
    EpicTableRow,
    ParsedEpic,
    Section,
    SpecFeature,
    SpecStory,
)

SPECS_FOLDER = "AOTPulse Specs"
SUMMARY_LIMIT = 250
_REQUIREMENT_REFS = re.compile(r"\s*\((FR-[^)]*)\)")
_PURPOSE = re.compile(r",\s+so\s+|\s+so\s+(?=(?:that\s+)?I\s)")


@dataclass(frozen=True)
class EpicSpecLinks:
    """``context`` is (spec prefix, user-story number or None for the whole
    spec); ``extra_stories`` are spec prefixes whose stories join the epic."""

    context: tuple[str, int | None] | None = None
    extra_stories: tuple[str, ...] = ()


def build_backlog(
    epics: Iterable[ParsedEpic],
    specs: Iterable[SpecFeature],
    links: Mapping[int, EpicSpecLinks],
) -> list[BacklogEpic]:
    by_prefix = {spec.folder.split("-")[0]: spec for spec in specs}
    return [_epic(epic, links.get(epic.number, EpicSpecLinks()), by_prefix) for epic in epics]


def story_summary(story: str) -> str:
    """The "As a ..., I want ..." clause, without its purpose or FR refs."""
    clause = _PURPOSE.split(_REQUIREMENT_REFS.sub("", story), maxsplit=1)[0].strip()
    clause = clause.rstrip(".")
    if len(clause) <= SUMMARY_LIMIT:
        return clause
    return clause[: SUMMARY_LIMIT - 1].rsplit(" ", 1)[0] + "…"


def _epic(epic: ParsedEpic, links: EpicSpecLinks, specs: dict) -> BacklogEpic:
    extras = [_spec(specs, prefix) for prefix in links.extra_stories]
    stories = [_row_story(epic.number, row) for row in epic.rows]
    stories += [_spec_story(spec, story) for spec in extras for story in spec.stories]
    sections = _non_empty(
        Section("Scope note", epic.note or ""),
        _context_section(specs, links.context),
        Section("Related specifications", items=tuple(map(_spec_ref, extras))),
    )
    return BacklogEpic(f"E{epic.number:02d}", epic.title, sections, tuple(stories))


def _non_empty(*sections: Section) -> tuple[Section, ...]:
    return tuple(section for section in sections if section.text or section.items)


def _spec(specs: dict, prefix: str) -> SpecFeature:
    if prefix not in specs:
        raise ValueError(f"no spec folder starting with {prefix!r} under {SPECS_FOLDER}/")
    return specs[prefix]


def _context_section(specs: dict, context: tuple[str, int | None] | None) -> Section:
    if context is None:
        return Section("")
    prefix, story_number = context
    spec = _spec(specs, prefix)
    if story_number is None:
        titles = tuple(f"User Story {s.number} ({s.priority}): {s.title}" for s in spec.stories)
        return Section(f"Specification: {spec.title}", spec.summary or "", titles)
    story = _spec_user_story(spec, story_number)
    heading = f"Specification: {spec.title} — User Story {story.number}: {story.title}"
    return Section(heading, story.narrative, story.acceptance, ordered=True)


def _spec_user_story(spec: SpecFeature, number: int) -> SpecStory:
    for story in spec.stories:
        if story.number == number:
            return story
    raise ValueError(f"{spec.folder} has no User Story {number}")


def _spec_ref(spec: SpecFeature) -> str:
    return f"{spec.title} ({_source(spec)})"


def _source(spec: SpecFeature) -> str:
    return f"{SPECS_FOLDER}/{spec.folder}/spec.md"


def _row_story(epic_number: int, row: EpicTableRow) -> BacklogStory:
    criteria = tuple(part.strip() for part in row.criteria.split("; ") if part.strip())
    sections = [Section("User story", row.story), Section("Acceptance criteria", items=criteria)]
    refs = _REQUIREMENT_REFS.findall(row.story)
    if refs:
        sections.append(Section("Requirements", ", ".join(refs)))
    sections.append(Section("Status", row.status))
    return BacklogStory(
        key=f"E{epic_number:02d}-S{row.number:02d}",
        summary=story_summary(row.story),
        sections=tuple(sections),
        labels=(_label(row.status),),
    )


def _spec_story(spec: SpecFeature, story: SpecStory) -> BacklogStory:
    prefix = spec.folder.split("-")[0]
    sections = _non_empty(
        Section("User story", story.narrative),
        Section("Why this priority", story.why or ""),
        Section("Independent test", story.independent_test or ""),
        Section("Acceptance scenarios", items=story.acceptance, ordered=True),
        Section("Source", _source(spec)),
    )
    return BacklogStory(
        key=f"S{prefix}-US{story.number}",
        summary=f"{spec.title} — {story.title}"[:SUMMARY_LIMIT],
        sections=sections,
        labels=(f"spec-{prefix}",),
        priority=story.priority,
    )


def _label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
