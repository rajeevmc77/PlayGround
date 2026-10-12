# ruff: noqa: E501  (inline CSS/HTML strings)
"""The report: a JSON file for programs and a self-contained HTML page for people that shows
every image (both sides, side by side), its verdict, and what the LLM check cost."""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from html import escape
from pathlib import Path
from urllib.parse import quote

from llm_compare.domain.durations import format_duration
from llm_compare.domain.models import LLM_VERDICTS, PairRecord, Usage, Verdict

_ROUTE = {
    Verdict.MATCH_PHASH: "hash",
    Verdict.IDENTICAL: "LLM",
    Verdict.DIFFERENT: "LLM",
    Verdict.ERROR: "LLM",
}


def _total_cost(rows: list[PairRecord], wasted: Usage) -> float | None:
    costs = [record.cost for record in rows]
    if wasted.input_tokens or wasted.output_tokens:
        costs.append(wasted.cost)
    return None if any(cost is None for cost in costs) else sum(costs)


def _usage_totals(rows: list[PairRecord], wasted: Usage, prefix: str = "") -> dict:
    input_tokens = sum(r.input_tokens for r in rows) + wasted.input_tokens
    output_tokens = sum(r.output_tokens for r in rows) + wasted.output_tokens
    return {
        f"{prefix}input_tokens": input_tokens,
        f"{prefix}output_tokens": output_tokens,
        f"{prefix}total_tokens": input_tokens + output_tokens,
        f"{prefix}cost": _total_cost(rows, wasted),
    }


def _spend(judged: list[PairRecord], wasted: Usage, settled: int) -> dict:
    """This run's spend (pairs judged now plus wasted calls) and the cumulative spend of
    every LLM verdict in the report, cached ones included; the per-pair cost and the hash's
    saving are based on the cumulative figure, so they stay known when everything is cached."""
    this_run = _usage_totals([r for r in judged if not r.cached], wasted)
    overall = _usage_totals(judged, wasted, "cumulative_")
    cost = overall["cumulative_cost"]
    per_pair = cost / len(judged) if cost is not None and judged else None
    return {
        **this_run,
        **overall,
        "cost_per_judged_pair": per_pair,
        "estimated_saved_cost": per_pair * settled if per_pair is not None else None,
    }


def _tally(records: list[PairRecord], judged: list[PairRecord]) -> dict:
    counts = Counter(record.verdict for record in records)
    return {
        "total_rows": len(records),
        "counts": {verdict.value: counts[verdict] for verdict in Verdict},
        "judged_by_llm": len(judged),
        "cached_hits": sum(record.cached for record in judged),
        "settled_by_hash": counts[Verdict.MATCH_PHASH],
    }


def _pairs_per_minute(live_pairs: int, judging_seconds: float) -> float | None:
    if live_pairs == 0 or judging_seconds <= 0:
        return None
    return live_pairs / (judging_seconds / 60)


def _timing(
    judged: list[PairRecord], scoring: float, judging: float, call_seconds: Sequence[float]
) -> dict:
    """How long the run took: the two phases, and the model's response time per call (the
    limiter's waits and the backoff sleeps are not part of a call)."""
    live = sum(not record.cached for record in judged)
    return {
        "scoring_seconds": scoring,
        "judging_seconds": judging,
        "total_seconds": scoring + judging,
        "calls_timed": len(call_seconds),
        "avg_call_seconds": sum(call_seconds) / len(call_seconds) if call_seconds else None,
        "slowest_call_seconds": max(call_seconds, default=None),
        "pairs_per_minute": _pairs_per_minute(live, judging),
    }


def summarise(
    records: list[PairRecord],
    calls: int,
    wasted: Usage,
    scoring_seconds: float = 0.0,
    judging_seconds: float = 0.0,
    call_seconds: Sequence[float] = (),
) -> dict:
    judged = [record for record in records if record.verdict in LLM_VERDICTS]
    tally = _tally(records, judged)
    return {
        **tally,
        "calls": calls,
        **_spend(judged, wasted, tally["settled_by_hash"]),
        **_timing(judged, scoring_seconds, judging_seconds, call_seconds),
    }


def _rate_text(pairs_per_minute: float | None) -> str:
    if pairs_per_minute is None:
        return ""
    shown = f"{pairs_per_minute:.0f}" if pairs_per_minute >= 10 else f"{pairs_per_minute:.1f}"
    return f", {shown} pairs/min"


def _calls_text(summary: dict) -> str:
    count = summary["calls_timed"]
    if count == 0:
        return "no LLM calls"
    noun = "call" if count == 1 else "calls"
    return (
        f"{count} {noun} avg {format_duration(summary['avg_call_seconds'])} "
        f"slowest {format_duration(summary['slowest_call_seconds'])}"
        f"{_rate_text(summary['pairs_per_minute'])}"
    )


def format_time_line(summary: dict) -> str:
    """The one terminal line: the run's total, its two phases and what the calls looked like."""
    phases = (
        f"total {format_duration(summary['total_seconds'])} "
        f"(scoring {format_duration(summary['scoring_seconds'])}, "
        f"judging {format_duration(summary['judging_seconds'])})"
    )
    return f"time: {phases}, {_calls_text(summary)}"


def _row(record: PairRecord) -> dict:
    row = asdict(record)
    row["verdict"] = record.verdict.value
    row["route"] = _ROUTE.get(record.verdict, "—")
    row["differences"] = list(record.differences)
    return row


def build_report(
    records: list[PairRecord],
    *,
    calls: int,
    wasted: Usage,
    model: str,
    prompt_version: str,
    generated_at: str,
    scoring_seconds: float = 0.0,
    judging_seconds: float = 0.0,
    call_seconds: Sequence[float] = (),
) -> dict:
    return {
        "generated_at": generated_at,
        "model": model,
        "prompt_version": prompt_version,
        "summary": summarise(
            records, calls, wasted, scoring_seconds, judging_seconds, call_seconds
        ),
        "rows": [_row(record) for record in records],
    }


_STYLE = """
:root{--bg:#fff;--fg:#1d2330;--mute:#667085;--line:#e3e6ec;--card:#f6f7fa;
--ok:#1a7f4b;--bad:#c0392b;--warn:#b7791f;--info:#2b6cb0;--none:#718096}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14171f;--fg:#e6e9f0;
--mute:#9aa3b5;--line:#2a2f3c;--card:#1c202b;--ok:#4cc38a;--bad:#ff7b6b;--warn:#e0b04c;
--info:#6cb0ff;--none:#8a93a6}}
:root[data-theme=dark]{--bg:#14171f;--fg:#e6e9f0;--mute:#9aa3b5;--line:#2a2f3c;--card:#1c202b;
--ok:#4cc38a;--bad:#ff7b6b;--warn:#e0b04c;--info:#6cb0ff;--none:#8a93a6}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:14px/1.45 system-ui,-apple-system,sans-serif}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mute);margin-bottom:14px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;min-width:120px}
.card b{display:block;font-size:18px}.card span{color:var(--mute);font-size:12px}
.tools{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
select,input{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}
th{position:sticky;top:0;background:var(--card);font-size:12px;color:var(--mute)}
td img{max-width:260px;max-height:200px;border:1px solid var(--line);background:#fff;display:block}
.cap,.none{color:var(--mute);font-size:12px}.key{font-family:ui-monospace,monospace;font-size:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;
border:1px solid currentColor}
.v-MATCH_PHASH,.v-IDENTICAL{color:var(--ok)}.v-DIFFERENT,.v-ERROR{color:var(--bad)}
.v-SKIPPED{color:var(--warn)}.v-WEB_ONLY{color:var(--info)}
ul{margin:4px 0 0 18px;padding:0}.num{white-space:nowrap}
"""

_SCRIPT = """
const rows=[...document.querySelectorAll('tbody tr')];
const verdict=document.getElementById('verdict'),query=document.getElementById('q');
function apply(){const v=verdict.value,q=query.value.toLowerCase();
for(const r of rows){r.hidden=!((v==='ALL'||r.dataset.verdict===v)&&(!q||r.dataset.key.includes(q)));}}
verdict.addEventListener('change',apply);query.addEventListener('input',apply);
"""


def _money(value: float | None) -> str:
    return "cost unavailable" if value is None else f"${value:.5f}"


def _src(path: str, prefix: str) -> str:
    return escape(prefix + quote(path), quote=True)


def _image_cell(path: str | None, prefix: str, sent: list | None, label: str) -> str:
    if not path:
        return "<span class='none'>—</span>"
    caption = f"<div class='cap'>sent {sent[0]}×{sent[1]}</div>" if sent else ""
    source = _src(path, prefix)
    alt = escape(label, quote=True)
    return (
        f'<a href="{source}" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="{source}" alt="{alt}"></a>{caption}'
    )


def _details(row: dict) -> str:
    parts = []
    if row["score"] is not None:
        parts.append(f"<div class='cap'>hash {row['score']:.1f}%</div>")
    if row["differences"]:
        items = "".join(f"<li>{escape(text)}</li>" for text in row["differences"])
        parts.append(f"<ul>{items}</ul>")
    if row["message"]:
        parts.append(f"<div>{escape(row['message'])}</div>")
    return "".join(parts) or "<span class='none'>—</span>"


def _usage(row: dict) -> str:
    if row["verdict"] not in ("IDENTICAL", "DIFFERENT"):
        return "<span class='none'>—</span>"
    cached = " · cached" if row["cached"] else ""
    batch = f"batch {row['batch_id']}" if row["batch_id"] is not None else "earlier run"
    took = "" if row["call_seconds"] is None else f" · {format_duration(row['call_seconds'])}"
    return (
        f"{row['input_tokens']:,} in / {row['output_tokens']:,} out<br>"
        f"{_money(row['cost'])}<div class='cap'>{batch}{took}{cached}</div>"
    )


def _row_html(row: dict, prefix: str) -> str:
    verdict = row["verdict"]
    key = escape(row["key"].lower(), quote=True)
    pdf_label, web_label = (f"{side} image {row['key']}" for side in ("PDF", "Web"))
    badge = f"<span class='badge v-{verdict}'>{verdict}</span><div class='cap'>{row['route']}</div>"
    cells = [
        f"<td class='key'>{escape(row['key'])}</td>",
        f"<td>{_image_cell(row['pdf_path'], prefix, row['sent_pdf'], pdf_label)}</td>",
        f"<td>{_image_cell(row['web_path'], prefix, row['sent_web'], web_label)}</td>",
        f"<td>{badge}</td>",
        f"<td>{_details(row)}</td>",
        f"<td class='num'>{_usage(row)}</td>",
    ]
    return f"<tr data-verdict='{verdict}' data-key='{key}'>{''.join(cells)}</tr>"


def _time_cards(summary: dict) -> list[tuple[str, str]]:
    return [
        ("run time", format_duration(summary["total_seconds"])),
        ("scoring", format_duration(summary["scoring_seconds"])),
        ("judging (LLM)", format_duration(summary["judging_seconds"])),
        ("avg call (completed)", format_duration(summary["avg_call_seconds"])),
        ("slowest call (completed)", format_duration(summary["slowest_call_seconds"])),
    ]


_COMPLETED_ONLY = "completed calls only: failed attempts are not timed"
_CARD_TITLES = {
    "LLM calls (attempts)": "attempts, including failed ones",
    "avg call (completed)": _COMPLETED_ONLY,
    "slowest call (completed)": _COMPLETED_ONLY,
}


def _card(label: str, value: str) -> str:
    title = f" title='{_CARD_TITLES[label]}'" if label in _CARD_TITLES else ""
    return f"<div class='card'{title}><b>{value}</b><span>{label}</span></div>"


def _cards(summary: dict) -> str:
    cards = [
        ("images", f"{summary['total_rows']:,}"),
        ("settled by hash (free)", f"{summary['settled_by_hash']:,}"),
        ("judged by LLM", f"{summary['judged_by_llm']:,}"),
        ("from cache", f"{summary['cached_hits']:,}"),
        ("LLM calls (attempts)", f"{summary['calls']:,}"),
        *_time_cards(summary),
        ("input tokens", f"{summary['input_tokens']:,}"),
        ("output tokens", f"{summary['output_tokens']:,}"),
        ("total tokens", f"{summary['total_tokens']:,}"),
        ("cost this run", _money(summary["cost"])),
        ("all judged verdicts: tokens", f"{summary['cumulative_total_tokens']:,}"),
        ("all judged verdicts: cost", _money(summary["cumulative_cost"])),
        ("cost per judged pair", _money(summary["cost_per_judged_pair"])),
        ("est. saved by hash", _money(summary["estimated_saved_cost"])),
    ]
    return "".join(_card(label, value) for label, value in cards)


def _chips(counts: dict) -> str:
    chips = "".join(f"<span class='badge v-{v}'>{v} {n}</span>" for v, n in counts.items())
    return f"<div class='cards'>{chips}</div>"


def _verdict_options(counts: dict) -> str:
    options = "".join(f"<option value='{v}'>{v} ({n})</option>" for v, n in counts.items())
    return f"<option value='ALL'>All verdicts</option>{options}"


def render_html(report: dict, asset_prefix: str = "") -> str:
    summary = report["summary"]
    body = "\n".join(_row_html(row, asset_prefix) for row in report["rows"])
    head = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>LLM Image Report</title><style>{_STYLE}</style></head><body>"
    )
    title = (
        f"<h1>LLM image comparison</h1><div class='sub'>model {escape(report['model'])} · "
        f"prompt {escape(report['prompt_version'])} · {escape(report['generated_at'])}</div>"
    )
    tools = (
        f"<div class='tools'><select id='verdict' aria-label='Filter by verdict'>{_verdict_options(summary['counts'])}</select>"
        "<input id='q' type='search' aria-label='Search by unified number' "
        "placeholder='Search unified number'></div>"
    )
    table = (
        "<div class='wrap'><table><thead><tr><th>Unified number</th><th>PDF image</th>"
        "<th>Web image</th><th>Verdict</th><th>Details</th><th>Tokens / cost</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )
    cards = f"<div class='cards'>{_cards(summary)}</div>"
    return f"{head}{title}{cards}{_chips(summary['counts'])}{tools}{table}<script>{_SCRIPT}</script></body></html>"


def write_report(report: dict, output_dir: Path, asset_prefix: str = "") -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "llm_image_compare.json"
    html_path = output_dir / "llm_image_report.html"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report, asset_prefix), encoding="utf-8")
    return json_path, html_path
