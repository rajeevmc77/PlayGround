# ruff: noqa: E501  (inline CSS/HTML strings)
"""The report: a JSON file for programs and a self-contained HTML page for people that shows
every image (both sides, side by side), its verdict, and what the LLM check cost."""

import json
from collections import Counter
from dataclasses import asdict
from html import escape
from pathlib import Path
from urllib.parse import quote

from llm_compare.domain.models import LLM_VERDICTS, PairRecord, Usage, Verdict

_ROUTE = {
    Verdict.MATCH_PHASH: "hash",
    Verdict.IDENTICAL: "LLM",
    Verdict.DIFFERENT: "LLM",
    Verdict.ERROR: "LLM",
}


def _total_cost(live: list[PairRecord], wasted: Usage) -> float | None:
    costs = [record.cost for record in live]
    if wasted.input_tokens or wasted.output_tokens:
        costs.append(wasted.cost)
    return None if any(cost is None for cost in costs) else sum(costs)


def _spend(live: list[PairRecord], wasted: Usage, settled: int) -> dict:
    """Tokens and cost of the pairs judged this run plus the wasted calls."""
    cost = _total_cost(live, wasted)
    per_pair = cost / len(live) if cost is not None and live else None
    return {
        "input_tokens": sum(r.input_tokens for r in live) + wasted.input_tokens,
        "output_tokens": sum(r.output_tokens for r in live) + wasted.output_tokens,
        "cost": cost,
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


def summarise(records: list[PairRecord], calls: int, wasted: Usage) -> dict:
    judged = [record for record in records if record.verdict in LLM_VERDICTS]
    live = [record for record in judged if not record.cached]
    tally = _tally(records, judged)
    return {**tally, "calls": calls, **_spend(live, wasted, tally["settled_by_hash"])}


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
) -> dict:
    return {
        "generated_at": generated_at,
        "model": model,
        "prompt_version": prompt_version,
        "summary": summarise(records, calls, wasted),
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


def _image_cell(path: str | None, prefix: str, sent: list | None) -> str:
    if not path:
        return "<span class='none'>—</span>"
    caption = f"<div class='cap'>sent {sent[0]}×{sent[1]}</div>" if sent else ""
    source = _src(path, prefix)
    return (
        f'<a href="{source}" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="{source}" alt=""></a>{caption}'
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
    return (
        f"{row['input_tokens']:,} in / {row['output_tokens']:,} out<br>"
        f"{_money(row['cost'])}<div class='cap'>{batch}{cached}</div>"
    )


def _row_html(row: dict, prefix: str) -> str:
    verdict = row["verdict"]
    key = escape(row["key"].lower(), quote=True)
    badge = f"<span class='badge v-{verdict}'>{verdict}</span><div class='cap'>{row['route']}</div>"
    cells = [
        f"<td class='key'>{escape(row['key'])}</td>",
        f"<td>{_image_cell(row['pdf_path'], prefix, row['sent_pdf'])}</td>",
        f"<td>{_image_cell(row['web_path'], prefix, row['sent_web'])}</td>",
        f"<td>{badge}</td>",
        f"<td>{_details(row)}</td>",
        f"<td class='num'>{_usage(row)}</td>",
    ]
    return f"<tr data-verdict='{verdict}' data-key='{key}'>{''.join(cells)}</tr>"


def _cards(summary: dict) -> str:
    cards = [
        ("images", f"{summary['total_rows']:,}"),
        ("settled by hash (free)", f"{summary['settled_by_hash']:,}"),
        ("judged by LLM", f"{summary['judged_by_llm']:,}"),
        ("from cache", f"{summary['cached_hits']:,}"),
        ("LLM calls", f"{summary['calls']:,}"),
        ("input tokens", f"{summary['input_tokens']:,}"),
        ("output tokens", f"{summary['output_tokens']:,}"),
        ("cost this run", _money(summary["cost"])),
        ("cost per judged pair", _money(summary["cost_per_judged_pair"])),
        ("est. saved by hash", _money(summary["estimated_saved_cost"])),
    ]
    return "".join(
        f"<div class='card'><b>{value}</b><span>{label}</span></div>" for label, value in cards
    )


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
        f"<div class='tools'><select id='verdict'>{_verdict_options(summary['counts'])}</select>"
        "<input id='q' type='search' placeholder='Search unified number'></div>"
    )
    table = (
        "<div class='wrap'><table><thead><tr><th>Unified number</th><th>PDF image</th>"
        "<th>Web image</th><th>Verdict</th><th>Details</th><th>Tokens / cost</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )
    cards = f"<div class='cards'>{_cards(summary)}</div>"
    return f"{head}{title}{cards}{tools}{table}<script>{_SCRIPT}</script></body></html>"


def write_report(report: dict, output_dir: Path, asset_prefix: str = "") -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "llm_image_compare.json"
    html_path = output_dir / "llm_image_report.html"
    json_path.write_text(json.dumps(report, indent=2))
    html_path.write_text(render_html(report, asset_prefix))
    return json_path, html_path
