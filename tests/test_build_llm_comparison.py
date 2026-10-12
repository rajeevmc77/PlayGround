import json
import os

import pytest

import build_llm_comparison
from build_llm_comparison import main
from llm_compare.analysis.judge import DspyPairJudge
from llm_compare.analysis.limiter import RateLimiter
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import PairVerdict, Usage, Verdict
from tests.llm_compare_support import png_bytes

PNG = png_bytes()
ENV = {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-x", "PATH": ""}


class AllIdentical:
    def __init__(self):
        self.calls = 0

    async def judge(self, pairs):
        self.calls += 1
        verdicts = [PairVerdict(n, Verdict.IDENTICAL, ()) for n in range(1, len(pairs) + 1)]
        return JudgeResult(verdicts, Usage(10 * len(pairs), len(pairs), 0.001))


def _source(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(exist_ok=True)
    (root / "web_images").mkdir(exist_ok=True)
    (root / "images/a.png").write_bytes(PNG)
    (root / "web_images/a.png").write_bytes(PNG)
    pdf = {"images": [{"image_path": "images/a.png", "unified_number": "A.Fig1"}], "volume": {}}
    web = {
        "images": [{"id": "a", "unified_number": "A.Fig1", "local_path": "web_images/a.png"}],
        "tree": {},
    }
    (root / "bcbc_pdf.json").write_text(json.dumps(pdf))
    (root / "bcbc_web.json").write_text(json.dumps(web))
    (root / "comparison.json").write_text(json.dumps({"counterparts": {}}))
    return root


def _args(source, *extra, out=None):
    return [
        "--source-dir",
        str(source),
        "--output-dir",
        str(out or source),
        "--config",
        str(source / "none.toml"),
        "--env-file",
        str(source / "none.env"),
        *extra,
    ]


def _report_rows(source):
    return json.loads((source / "llm_image_compare.json").read_text())["rows"]


def test_identical_images_are_settled_by_the_hash_and_still_reported(tmp_path):
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source), env=ENV, judge=judge, now="2026-10-12T00:00:00+00:00") == 0
    assert judge.calls == 0
    report = json.loads((source / "llm_image_compare.json").read_text())
    assert [row["verdict"] for row in report["rows"]] == ["MATCH_PHASH"]
    assert (source / "llm_image_report.html").exists()


def test_a_pair_the_hash_cannot_settle_is_judged_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source), env=ENV, judge=judge, now="t") == 0
    assert judge.calls == 1
    row = _report_rows(source)[0]
    assert row["verdict"] == "IDENTICAL" and row["input_tokens"] == 10
    assert (source / "llm_compare" / "cache.json").exists()
    assert main(_args(source), env=ENV, judge=judge, now="t") == 0
    assert judge.calls == 1  # the second run is served from the cache


def test_the_report_references_images_relative_to_the_output_directory(tmp_path):
    source = _source(tmp_path / "src")
    out = tmp_path / "out"
    assert main(_args(source, out=out), env=ENV, judge=AllIdentical(), now="t") == 0
    assert 'src="../src/images/a.png"' in (out / "llm_image_report.html").read_text()


def test_dry_run_calls_nothing_writes_no_report_and_needs_no_key(tmp_path, capsys):
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source, "--dry-run"), env={"PATH": ""}, judge=judge) == 0
    assert judge.calls == 0 and not (source / "llm_image_report.html").exists()
    assert "LLM calls" in capsys.readouterr().out


def test_dry_run_keeps_litellm_off_the_network_by_using_its_local_price_map(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    assert main(_args(_source(tmp_path), "--dry-run"), env={"PATH": ""}) == 0
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def test_dry_run_respects_an_explicit_price_map_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    assert main(_args(_source(tmp_path), "--dry-run"), env={"PATH": ""}) == 0
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "False"


def test_a_missing_key_or_model_exits_before_any_call(tmp_path, capsys):
    source = _source(tmp_path)
    assert main(_args(source), env={"PATH": ""}, judge=None) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err
    assert main(_args(source), env={"GEMINI_API_KEY": "k"}, judge=None) == 2
    assert "GEMINI_MODEL" in capsys.readouterr().err
    assert not (source / "llm_image_report.html").exists()


def test_the_api_key_value_is_never_printed(tmp_path, capsys):
    source = _source(tmp_path)
    secret = {"GEMINI_API_KEY": "s3cr3t-key-value", "PATH": ""}
    assert main(_args(source), env=secret, judge=None) == 2
    captured = capsys.readouterr()
    assert "s3cr3t-key-value" not in captured.out + captured.err


def test_missing_input_files_exit_with_a_clear_message(tmp_path, capsys):
    assert main(_args(tmp_path), env=ENV, judge=AllIdentical()) == 2
    assert "bcbc_pdf.json" in capsys.readouterr().err


def test_an_invalid_config_file_exits_with_its_message(tmp_path, capsys):
    source = _source(tmp_path)
    (source / "bad.toml").write_text("rpm = 0")
    args = [
        "--source-dir",
        str(source),
        "--config",
        str(source / "bad.toml"),
        "--env-file",
        str(source / "none.env"),
    ]
    assert main(args, env=ENV, judge=AllIdentical()) == 2
    assert "rpm" in capsys.readouterr().err


class Interrupting:
    async def judge(self, pairs):
        raise KeyboardInterrupt


def test_an_interrupted_run_still_reports_with_unfinished_pairs_as_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=Interrupting(), now="t") == 130
    row = _report_rows(source)[0]
    assert row["verdict"] == "ERROR" and "interrupted" in row["message"]


def test_the_interrupted_rerun_uses_a_fresh_rate_limiter(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    made = []

    class Spy(RateLimiter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(build_llm_comparison, "RateLimiter", Spy)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=Interrupting(), now="t") == 130
    assert len(made) == 2 and made[0] is not made[1]


def test_a_negative_limit_is_rejected_by_the_argument_parser_before_any_work(tmp_path, capsys):
    source = _source(tmp_path)
    judge = AllIdentical()
    with pytest.raises(SystemExit) as raised:
        main(_args(source, "--limit", "-1"), env=ENV, judge=judge)
    assert raised.value.code == 2 and judge.calls == 0
    assert "limit" in capsys.readouterr().err
    assert not (source / "llm_image_report.html").exists()


def test_a_non_numeric_limit_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as raised:
        main(_args(_source(tmp_path), "--limit", "many"), env=ENV, judge=AllIdentical())
    assert raised.value.code == 2


def test_a_limit_of_zero_judges_nothing_and_skips_the_pairs_for_the_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source, "--limit", "0"), env=ENV, judge=judge, now="t") == 0
    row = _report_rows(source)[0]
    assert judge.calls == 0 and row["verdict"] == "SKIPPED"
    assert "not judged: --limit reached" in row["message"]


def test_calibrate_prints_a_recommendation_and_saves_the_variants(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    assert main(_args(source, "--calibrate", "1"), env=ENV, judge=AllIdentical()) == 0
    assert "recommended max_edge" in capsys.readouterr().out
    saved = json.loads((source / "llm_compare" / "calibration.json").read_text())
    assert saved[0]["variant"].startswith("original size")
    assert saved[0]["verdicts"] == {"pdf:images/a.png": "IDENTICAL"}
    assert not (source / "llm_image_report.html").exists()
    assert not (source / "llm_compare" / "cache.json").exists()


@pytest.mark.parametrize("value", ["0", "-3", "many"])
def test_an_invalid_calibrate_count_is_rejected_before_any_work(tmp_path, value):
    source = _source(tmp_path)
    judge = AllIdentical()
    with pytest.raises(SystemExit) as raised:
        main(_args(source, "--calibrate", value), env=ENV, judge=judge)
    assert raised.value.code == 2 and judge.calls == 0
    assert not (source / "llm_compare").exists()


def test_with_a_key_and_a_model_the_credential_check_passes():
    config = build_llm_comparison.LlmCompareConfig(api_key="k", model="gemini-x")
    assert build_llm_comparison._check_credentials(config, None) is None


def test_the_real_judge_is_a_dspy_judge_for_the_configured_model():
    config = build_llm_comparison.LlmCompareConfig(api_key="k", model="gemini-x")
    assert isinstance(build_llm_comparison._real_judge(config), DspyPairJudge)
