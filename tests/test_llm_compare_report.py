import json

import pytest

from llm_compare.domain.models import PairRecord, Usage, Verdict
from llm_compare.output.report import build_report, render_html, summarise, write_report


def _rec(key, verdict, **extra):
    base = {
        "row_id": f"pdf:{key}",
        "key": key,
        "verdict": verdict,
        "pdf_path": f"images/{key}.png",
        "web_path": f"web_images/{key}.jpg",
    }
    return PairRecord(**{**base, **extra})


def _records():
    return [
        _rec("A.Fig1", Verdict.MATCH_PHASH, score=97.0),
        _rec(
            "A.Fig2",
            Verdict.IDENTICAL,
            score=60.0,
            input_tokens=1000,
            output_tokens=50,
            cost=0.002,
            batch_id=1,
            sent_pdf=(40, 30),
            sent_web=(80, 60),
        ),
        _rec(
            "A.Fig3",
            Verdict.DIFFERENT,
            score=30.0,
            input_tokens=2000,
            output_tokens=100,
            cost=0.004,
            batch_id=1,
            differences=("label 'X' missing",),
        ),
        _rec(
            "A.Fig4",
            Verdict.IDENTICAL,
            score=70.0,
            input_tokens=500,
            output_tokens=10,
            cost=0.001,
            cached=True,
        ),
        _rec("A.Fig5", Verdict.SKIPPED, web_path=None, message="no web counterpart"),
        PairRecord(
            row_id="web:w",
            key="W.Fig1",
            verdict=Verdict.WEB_ONLY,
            pdf_path=None,
            web_path="web_images/w.jpg",
        ),
        _rec("A.Fig6", Verdict.ERROR, message="no usable verdict after retries"),
    ]


def test_summary_counts_every_verdict_and_totals_only_this_runs_spend():
    summary = summarise(_records(), calls=2, wasted=Usage(100, 5, 0.0005))
    assert summary["total_rows"] == 7
    assert summary["counts"] == {
        "MATCH_PHASH": 1,
        "IDENTICAL": 2,
        "DIFFERENT": 1,
        "SKIPPED": 1,
        "WEB_ONLY": 1,
        "ERROR": 1,
    }
    assert (summary["judged_by_llm"], summary["cached_hits"], summary["settled_by_hash"]) == (
        3,
        1,
        1,
    )
    assert summary["calls"] == 2
    assert (summary["input_tokens"], summary["output_tokens"]) == (3100, 155)
    assert summary["cost"] == pytest.approx(0.0065)
    assert summary["cost_per_judged_pair"] == pytest.approx(0.0065 / 2)
    assert summary["estimated_saved_cost"] == pytest.approx(0.0065 / 2)


def test_unknown_cost_stays_unknown_everywhere():
    records = [
        _rec("A.Fig2", Verdict.IDENTICAL, input_tokens=10, output_tokens=1, cost=None, batch_id=1)
    ]
    summary = summarise(records, calls=1, wasted=Usage())
    assert summary["cost"] is None and summary["cost_per_judged_pair"] is None
    assert "cost unavailable" in render_html(
        build_report(
            records, calls=1, wasted=Usage(), model="m", prompt_version="v", generated_at="t"
        )
    )


def test_an_empty_run_is_valid():
    report = build_report(
        [], calls=0, wasted=Usage(), model="m", prompt_version="v", generated_at="t"
    )
    assert report["summary"]["total_rows"] == 0
    assert render_html(report).count("<tr data-verdict") == 0


def _html(records=None, prefix=""):
    report = build_report(
        records or _records(),
        calls=2,
        wasted=Usage(),
        model="gemini-x",
        prompt_version="abc123",
        generated_at="2026-10-12T00:00:00+00:00",
    )
    return render_html(report, prefix), report


def test_every_record_gets_a_row_with_its_verdict():
    html, report = _html()
    assert html.count("<tr data-verdict") == 7 == len(report["rows"])
    for verdict in ("MATCH_PHASH", "IDENTICAL", "DIFFERENT", "SKIPPED", "WEB_ONLY", "ERROR"):
        assert f"v-{verdict}" in html


def test_both_images_are_shown_with_their_sent_size_and_a_web_only_row_shows_one():
    html, _ = _html()
    assert 'src="images/A.Fig2.png"' in html and 'src="web_images/A.Fig2.jpg"' in html
    assert "sent 40×30" in html and "sent 80×60" in html
    assert 'src="web_images/w.jpg"' in html and "images/W.Fig1" not in html


def test_the_asset_prefix_is_applied_to_every_image():
    html, _ = _html(prefix="../src_out/")
    assert 'src="../src_out/images/A.Fig2.png"' in html


def test_differences_message_and_numbers_are_shown():
    html, _ = _html()
    assert "label &#x27;X&#x27; missing" in html
    assert "no web counterpart" in html and "no usable verdict after retries" in html
    assert "1,000" in html and "cached" in html


def test_special_characters_in_keys_and_messages_are_escaped_and_searchable():
    nasty = _rec(
        "B.A-9.8.8.6.(1).Fig4 <&>",
        Verdict.DIFFERENT,
        differences=("<script>alert(1)</script>",),
        input_tokens=1,
        output_tokens=1,
        cost=0.0,
        batch_id=1,
    )
    html, _ = _html([nasty])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "B.A-9.8.8.6.(1).Fig4 &lt;&amp;&gt;" in html
    assert "data-key='b.a-9.8.8.6.(1).fig4 &lt;&amp;&gt;'" in html


def test_the_header_states_tokens_cost_and_the_free_hash_settlements():
    html, _ = _html()
    for text in ("gemini-x", "abc123", "3,000", "$0.00600", "settled by hash"):
        assert text in html


def test_write_report_creates_both_files(tmp_path):
    _, report = _html()
    json_path, html_path = write_report(report, tmp_path, asset_prefix="")
    assert json.loads(json_path.read_text())["summary"]["total_rows"] == 7
    assert html_path.name == "llm_image_report.html" and "<table" in html_path.read_text()
