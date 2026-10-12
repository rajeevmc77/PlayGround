"""The one role the runner needs from an LLM: judge a batch of prepared pairs."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from llm_compare.domain.models import PairVerdict, PreparedPair, Usage


@dataclass(frozen=True)
class JudgeResult:
    verdicts: list[PairVerdict]
    usage: Usage = field(default_factory=Usage)


class PairJudge(Protocol):
    async def judge(self, pairs: Sequence[PreparedPair]) -> JudgeResult: ...
