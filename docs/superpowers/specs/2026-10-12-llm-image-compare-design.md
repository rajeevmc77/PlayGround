# LLM visual image comparison (DSPy) - design

Date: 2026-10-12 · Status: draft for review

## Purpose

The comparison engine decides whether a PDF image and its web counterpart show the
same thing with perceptual hashes (`src/comparison/image_similarity.py`). A hash
cannot say *what* differs, and it is unsure on many real pairs. This feature adds a
cost-controlled visual check by a multimodal LLM, through DSPy, for the pairs the
hash cannot settle, and a report that shows **every image, its verdict, and what the
check cost**.

Success looks like:

- Every PDF image and every web image appears in one report with its verdict.
- Pairs the hash settles cost nothing; the rest are judged by the LLM from the
  agreed Gemini prompt (content identical or different, ignoring resolution,
  format, scaling and compression).
- The report states tokens and cost, per pair and in total.
- A full run stays inside the provider's rate limits, uses few round trips, and a
  re-run or an interrupted run re-spends nothing on pairs already judged.

Non-goals: changing the tree's ✓/✗ or `comparison.json`; replacing the hash; judging
text; training or tuning a model. The LLM verdict is a second opinion kept in its
own files.

## Measured baseline (2026-10-12, current `output/`)

| | Pairs |
|---|---|
| Paired images (same number, or via `counterparts`) | 521 |
| No web counterpart / unreadable | 66 / 1 |
| phash score >= 90% (matched, no LLM) | 276 |
| phash score < 90% (sent to the LLM) | **245** (161 figures, 84 equations) |

PDF rasters: median 191x130 px, max 1232x962. Web images: median 593x396, max
2366x2256.

## Package layout

New code follows the `mo_toc`/`web_toc` split. Domain logic stays free of HTTP, file
I/O and DSPy; the LLM sits behind one small interface.

```
src/llm_compare/
  domain/models.py        ImagePair, PreparedImage, PairVerdict, Usage, PairRecord
  domain/selection.py     route each pair: matched-by-hash / to-LLM / skipped   (pure)
  domain/batching.py      pack pairs into calls by pair and token budget        (pure)
  domain/costing.py       split a call's tokens/cost across its pairs           (pure)
  parsing/preprocess.py   normalise one image's bytes                           (Pillow)
  parsing/pair_source.py  build ImagePairs from bcbc_pdf/bcbc_web/comparison.json
  analysis/judge.py       PairJudge protocol + DSPy implementation
  analysis/limiter.py     async RPM/TPM limiter, retry/backoff
  analysis/runner.py      orchestrate: select -> prepare -> batch -> judge -> merge
  output/cache.py         verdict cache keyed by content hash
  output/report.py        llm_image_compare.json + llm_image_report.html
src/build_llm_comparison.py   CLI entry point
```

`PairJudge` is the single seam: `async judge(batch) -> list[PairVerdict]` plus the
call's `Usage`. Tests inject a fake; only the DSPy implementation imports `dspy`.

## 1. Pair source and selection

- Pairs come from the existing pairing: a PDF image's `unified_number`, or its
  `counterparts` entry (a `null` entry means no web counterpart). Pixels load with
  `comparison.asset_loader`.
- The hash score is `compare_images(...)` from `comparison.image_similarity` (the
  better of plain and ink phash for figures; plain for equations).
- Routing, by `select_route(score)`:
  - `score >= 90.0` -> `MATCH_PHASH` (no LLM). The boundary is inclusive.
  - `score < 90.0` -> sent to the LLM. This applies to equations as well; the old
    80%/70% thresholds and the OCR/ink-correlation rescues are not used here.
  - no web counterpart, no `unified_number`, or an unreadable file -> `SKIPPED`
    with a stated reason; no call is made.
- Every web image with no PDF partner is listed as `WEB_ONLY`.

## 2. Preprocessing (cost without losing content)

Goal: fewer image tokens per call without hiding any text, line or label.

For each image, in order:

1. Decode; flatten any alpha onto white; convert to RGB. Colour is kept, since a
   figure can encode meaning in it.
2. Trim blank margins with the existing `autocrop_to_content`, so padding is not
   paid for.
3. Fit inside a square box of `max_edge` px, **scaling down only** (Lanczos). Small
   PDF rasters are not enlarged.
4. Encode as PNG (lossless, text stays crisp). Image tokens are billed by pixel
   dimensions, not file bytes, so lossy encoding would add risk and save nothing.

`max_edge` is chosen by evidence, not guessed: a calibration run
(`--calibrate N`) judges N sampled pairs at 768, 1024 and original size and reports
verdict agreement and tokens per setting; the smallest cap whose verdicts match the
original is written to config. The same run compares batch size 1 against the
default batch size to confirm batching does not change verdicts.

## 3. Prompt and DSPy signature

The user's Gemini prompt is the signature's instruction text, verbatim, with one
added paragraph stating that the call holds several numbered pairs and each pair is
judged independently.

```
class CompareImagePairs(dspy.Signature):
    """<the agreed instruction prompt>"""
    pairs: list[ImagePair]            # labelled "PAIR n", image A (PDF) then B (web)
    verdicts: list[PairVerdict]       # one per pair, same ids

class PairVerdict(BaseModel):
    pair_id: int
    verdict: Literal["IDENTICAL", "DIFFERENT"]
    differences: list[str]            # empty when IDENTICAL
```

Temperature 0. The instruction text is hashed into a `prompt_version` used by the
cache, so editing it invalidates old verdicts.

## 4. Batching (fewer round trips)

- `pack(pairs, max_pairs, max_input_tokens)` fills each call greedily in a stable
  order until either budget would be exceeded. Defaults: 6 pairs, and an input
  budget well below the model's context.
- Image token estimates come from the preprocessed dimensions using the model's
  tiling rule, held in config and verified by the calibration run against the
  usage the API reports. The instruction text is paid once per call.
- A response with a missing id, a duplicate id, or malformed output is not
  accepted as is: the affected pairs are re-queued as single-pair calls, at most
  twice, then recorded as `ERROR` with the message. Pairs that were answered are kept.

## 5. Async calls within rate limits

- DSPy async calls (`acall`) under `asyncio`, with a worker count cap.
- `RateLimiter(rpm, tpm)` is a sliding one-minute window. Before a call it reserves
  the estimated tokens, waits if either budget would be exceeded, and after the
  call corrects the reservation with the actual usage.
- 429 and 5xx responses retry with exponential backoff and jitter, honouring a
  `Retry-After` value when present; other 4xx responses fail the batch without retry.
- Limits (RPM, TPM, workers) come from config, not code.

## 6. Tokens and cost

- Tokens and cost per call are read from the DSPy/LiteLLM call history (prompt,
  completion, and total tokens; cost).
- If LiteLLM has no price for the model, the per-million-token input and output
  prices from config are used; if neither exists the report shows tokens and a
  clear "cost unavailable" instead of a wrong number.
- A batch's usage is split across its pairs in proportion to each pair's image
  token estimate, so per-pair figures sum exactly to the call total.
- Cache: `output/llm_compare/cache.json` maps `sha256(image A, image B,
  prompt_version, model)` to a verdict and its usage. A hit costs nothing and is
  marked `cached` in the report; interrupted runs resume from it.
- `--dry-run` prints route counts, number of calls, estimated tokens and estimated
  cost, makes no API call and writes no report.

## 7. Report

Outputs: `output/llm_image_compare.json` (machine-readable) and
`output/llm_image_report.html` (self-contained page; images by relative path to the
existing `output/images/` and `output/web_images/`).

**It shows all images.** One row per PDF image and per web-only image, so nothing is
hidden, whatever route it took:

| Verdict | Meaning | Shown |
|---|---|---|
| `MATCH_PHASH` | hash >= 90% | both images, score |
| `IDENTICAL` | LLM says the same content | both images, differences empty |
| `DIFFERENT` | LLM found differences | both images, the differences listed |
| `SKIPPED` | no counterpart / no number / unreadable | the image that exists, the reason |
| `WEB_ONLY` | web image no PDF image pairs with | the web image |
| `ERROR` | LLM call failed after retries | both images, the message |

Each row: unified number, PDF image and web image side by side (click to enlarge),
verdict badge, hash score, route, differences, and for LLM-judged rows the tokens
(input/output), cost, batch id and whether cached. A caption gives the size each
image was sent at.

Header summary: total images, count per verdict, pairs settled free by hash vs
judged by the LLM, calls made, input/output/total tokens, total cost, cost per
LLM-judged pair, and the estimated cost the hash step saved. Filter controls by
verdict and a search box on unified number.

## 8. Configuration

`GEMINI_API_KEY` and `GEMINI_MODEL` come from `.env` (already present, git-ignored);
a git-ignored `llm_compare_config.toml` (with a committed `.example`) holds
`hash_match_percent` (90), `max_edge`, `max_pairs_per_call`, `rpm`, `tpm`, `workers`,
and optional prices. Keys are never logged or written to output files.

## 9. Error handling

| Case | Behaviour |
|---|---|
| Unreadable / missing image file | `SKIPPED`, reason recorded, run continues |
| Missing API key | exit non-zero before any call, message names the variable |
| 429 / 5xx | backoff and retry; give up per pair as `ERROR` |
| Partial or malformed batch response | re-queue only the affected pairs singly |
| Ctrl-C | cache holds finished work; re-run resumes; report built from what exists |

## 10. Testing (TDD)

All unit tests use a fake `PairJudge` and fake clock; no network.

- selection: scores 89.99 / 90.0 / 100, equations, missing counterpart, `null`
  counterpart, unreadable bytes.
- preprocess: alpha flatten, margin trim, scale-down only (small image unchanged),
  aspect ratio kept, deterministic output.
- batching: budgets by pairs and by tokens, empty input, one oversize pair,
  stable order.
- costing: shares sum to the call total; zero and one-pair batches; missing price.
- limiter: never exceeds RPM/TPM in any window; correction on actual usage;
  backoff honours Retry-After; non-retryable errors surface.
- runner: missing id re-queue, retry ceiling, cache hit costs zero, resume.
- report: every PDF and web-only image has a row; summary totals equal row sums.
- one `slow`, opt-in test calls the real API on three pairs.

Definition of done follows `CLAUDE.md` (ruff, radon, vulture, pytest), and the work
goes through a worktree and a PR. `dspy` is added to `requirements.txt`; its API
(`acall`, usage/history fields, image type) is confirmed against the installed
version when implementation starts.

## Open points to settle during implementation

- The model's actual image tiling and price are measured by the calibration run;
  config values start as conservative estimates.
- Default `max_pairs_per_call` is set from the calibration comparison, not fixed
  here.
