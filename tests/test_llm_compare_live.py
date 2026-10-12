"""Hits the real model on three pairs; skipped unless a key and the built output exist.
Run with: pytest -m slow tests/test_llm_compare_live.py"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from llm_compare.analysis.judge import DspyPairJudge
from llm_compare.analysis.pricing import resolve_prices
from llm_compare.analysis.runner import classify_pairs, prepare_pairs
from llm_compare.config import load_config, parse_dotenv
from llm_compare.domain.models import LLM_VERDICTS
from llm_compare.parsing.pair_source import build_pairs

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get("LLM_COMPARE_SOURCE_DIR", ROOT / "output"))
ENV_FILE = Path(os.environ.get("LLM_COMPARE_ENV_FILE", ROOT / ".env"))


def _load_bytes(relative: str) -> bytes | None:
    path = SOURCE / relative
    return path.read_bytes() if relative and path.is_file() else None


@pytest.mark.slow
def test_three_real_pairs_get_real_verdicts_and_usage():
    dotenv = parse_dotenv(ENV_FILE.read_text()) if ENV_FILE.is_file() else {}
    config = load_config("", os.environ, dotenv)
    if not (config.api_key and config.model and (SOURCE / "bcbc_pdf.json").is_file()):
        pytest.skip("needs GEMINI_API_KEY, GEMINI_MODEL and a built output/")
    pdf = json.loads((SOURCE / "bcbc_pdf.json").read_text())["images"]
    web = json.loads((SOURCE / "bcbc_web.json").read_text())["images"]
    counterparts = json.loads((SOURCE / "comparison.json").read_text())["counterparts"]
    scored = classify_pairs(build_pairs(pdf, web, counterparts), _load_bytes, 90.0).to_llm[:3]
    prepared = prepare_pairs(scored, config.max_edge, config.token_scale)
    judge = DspyPairJudge(config, resolve_prices(config))
    result = asyncio.run(judge.judge(prepared))
    assert len(result.verdicts) == 3
    assert all(v.verdict in LLM_VERDICTS for v in result.verdicts)
    assert result.usage.input_tokens > 0
