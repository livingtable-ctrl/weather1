# SHARED PREAMBLE — Line-by-Line Grade Audit
# Every grading agent receives this file in full before reading their assigned source file.

## Your Assignment

You are grading **one source file** from a live-money weather prediction trading bot.
You will not see the other files. Everything you need is in this preamble plus your
per-file module.

**What "grade" means:** Read every function line by line. For each function, produce a
score and a verdict. Do not skim. Do not skip. If a function is three lines long, those
three lines still get read and scored.

---

## System Context

Kalshi weather prediction trading bot. ~$815 balance, ~167 settled trades.
Single Windows process: SQLite predictions DB (`predictions.db`) + JSON paper ledger
(`paper_trades.json`).

**Two trade pipelines — every function belongs to one or both:**

- **Same-day** (`days_out=0`): METAR observation lock-in → Kelly sizing → order
  placement. Probabilities sharp, near 0 or 1. `CI_SCALE=1.0`.
- **Multi-day** (`days_out≥1`): GFS/ECMWF/ICON ensemble blend → temperature scaling →
  GBM bias correction → Platt calibration → market anchor → Kelly sizing → order.
  Probabilities smooth, 0.3–0.7.

A bug in the trade execution path has a direct dollar cost today.
A bug in the calibration path silently shrinks model edge over weeks.
A bug in balance/drawdown accounting produces wrong halts — or missing ones.

---

## Two Grading Tiers

**TIER 1** — Functions that directly affect trade placement, sizing, settlement, or
balance/drawdown accounting.
- Apply the full rubric.
- Full output block (see Output Format).
- Cannot score >6 with any silent failure mode.
- Cannot score >8 without meaningful test coverage (a test that imports the function
  and makes at least one non-trivial assertion about its output — not just an import check).
- Must include a failure scenario for any score ≤7.

**TIER 2** — Everything else: utilities, formatters, display helpers, logging, backup,
health checks.
- Same rubric, compressed one-line output.
- Fix required if score ≤6.
- Failure scenario required if score ≤4.

Your per-file module lists the TIER 1 functions in your file explicitly. Any function
not on that list is TIER 2.

---

## Rubric (1–10)

Score from **correctness + safety** first. Then apply deductions.

| Correctness + Safety situation | Starting range |
|---|---|
| Both flawless — all failure paths handled and logged | 9–10 |
| One non-fatal gap (missing log, one unguarded edge case) | 7–8 |
| One potentially-fatal gap (bad input could propagate silently) | 5–6 |
| Active bug on a plausible code path | 3–4 |
| Fundamental flaw or multiple active bugs | 1–2 |

**Deductions after base score (max −2 total across all deductions):**
- Logic hard to follow cold — non-obvious invariant with no comment: −1
- Redundant DB reads, N+1 queries, or unbounded data growth: −1
- Any system invariant missed (see Invariants table): −1 per missed invariant

The −2 cap is hard. If three invariants are missed, the cap still applies — but the
base score would already reflect the severity of missing invariants.

**Red flags — override base, instant cap at ≤4 regardless of other dimensions:**

| # | Red flag |
|---|---|
| RF1 | Exception caught without a log at WARNING or above |
| RF2 | Balance or position data read outside `_DATA_LOCK` before a write decision |
| RF3 | Metric query uses `FROM predictions` without `days_out` filter — and is not on the known-intentional list below |
| RF4 | A probability or dollar cost enters the Kelly formula without a `0 < p < 1` and `cost > 0` guard |
| RF5 | A trading-decision threshold is hardcoded when it should be read from `.env` |
| RF6 | A TIER 1 function with zero meaningful test coverage |

**Anti-inflation check:** Before submitting your scores for this file, re-read every
function you gave 8 or above. Ask: "Would a senior engineer trust this function with
$10,000 of someone else's money without reading it first?" If no, lower the score.
A correctly-calibrated median for a production trading bot is 6–7. Reserve 9–10 for
genuinely exemplary functions.

---

## Score Anchors

Use these to calibrate your scoring. Every score from 1–10 has a reference.

**10:** `atomic_write_json` using `os.replace()` (Windows-safe), writes to a
uniquely-named temp file, catches and logs WinError 32 at WARNING then retries, cleans
up temp on exception, has test coverage for happy path + WinError + crash-between-
write-and-rename.

**9:** `is_paused_drawdown()` — single responsibility, delegates to
`_drawdown_snapshot()`, returns a clean bool, no side effects, has test coverage.
One minor gap: no log line when returning True so the operator can't see the pause
reason without grepping logs.

**8:** A blend-weight application function that correctly dispatches same-day vs
multi-day paths using `days_out`, falls back with a WARNING log on exception, and has
test coverage for both paths. Gap: cache invalidation after weight change is in a
different function and not cross-referenced here.

**7:** A calibration query that correctly filters `days_out≥1` but catches a broad
`Exception` and logs at DEBUG instead of WARNING — operator can't see when calibration
data was unavailable without enabling debug logging.

**6:** A Brier computation querying `FROM predictions` without a `days_out` filter.
Correct today with few same-day trades; silently mixes METAR wins into multi-day
metrics as volume grows. No active bug yet.

**5:** Correct for all current inputs but has an untested edge case (empty position
list, all-identical ensemble) that would cause `ZeroDivisionError` or `KeyError` in
production. Bug has never fired but will at some volume threshold.

**4:** Exception handler catches a Kalshi API timeout and returns `0.5` without
logging. Caller sees a "valid" probability and places a trade at market odds.

**3:** Kelly sizing passes `blended_prob` to the formula without checking it's finite.
A degenerate ensemble returning `None` upstream propagates to NaN bet size.

**2:** A settlement function that marks a trade settled without enforcing the 24h gate —
could prematurely close positions, producing wrong P&L records.

**1:** `graduation_check()` that computes Brier from a query mixing same-day and
multi-day trades — allows live trading to start when the multi-day model is still poor,
as same-day METAR wins inflate the composite score past the gate threshold.

---

## System Invariants

Check each function against the invariants it is responsible for. Only check invariants
that apply to the function you are grading. A missed invariant costs −1 (still capped
at −2 total with other deductions).

| # | Invariant | What correct looks like |
|---|---|---|
| I1 | SQL same-day/multi-day separation | Metric queries use `multiday_predictions` view or explicit `AND (p.days_out IS NULL OR p.days_out >= 1)` or `AND p.days_out = 0` |
| I2 | Lock discipline | `_DATA_LOCK` acquired and held across the **entire** read-modify-write cycle — no gap between `_load()` and `_save()` |
| I3 | Atomic write | Uses `os.replace()` not `os.rename()` on Windows; writes to temp file first; temp file cleaned on exception |
| I4 | 24h settlement gate | **All** settlement paths check `close_time + 24h < now`; NULL `close_time` is skipped gracefully — applies to trades before 2026-05-28 which have NULL close_time |
| I5 | Kelly finite guard | `0 < blended_prob < 1` and `cost > 0` verified before Kelly formula — NaN or None must never reach Kelly |
| I6 | EMOS fallback | Gaussian EMOS path falls back gracefully when `emos_params.json` is absent — trade continues on the non-EMOS path |
| I7 | Degenerate ensemble guard | Returns `None` early when all ensemble members are identical — prevents junk probability from entering the blend |
| I8 | Effective balance for trade decisions | Any function that **gates or scales a trade** uses `_drawdown_snapshot()`, not raw `get_balance()`. Reporting functions (`get_max_drawdown_pct()`, display helpers) may use `get_balance()` — intentional. |
| I9 | days_out thread-through | In the cron scan path, `days_out` is carried from `analyze_trade()` → signal cache → order placement. Must not be re-derived or defaulted at any step. |
| I10 | Paper/live gate | `KALSHI_ENV` is checked before any code path that calls `client.place_order()` or `client._post()`. Viewing order books or reading positions does not require this gate. |

---

## Known-Intentional Patterns — Do NOT deduct for any of these

**SQL — intentionally unfiltered (these are correct by design):**
- `tracker.get_brier_by_days_out()` — segments by days_out in Python; needs all rows
- `tracker.get_history()` — trade history display; should show everything
- `tracker.sync_outcomes()` — must check ALL unsettled tickers regardless of days_out
- `tracker.get_market_calibration()` — measures Kalshi market prices vs outcomes
- `tracker.purge_old_predictions()` — operates on the raw table
- All schema migration functions — operate on the raw table
- `paper.get_all_trades()` — deliberately returns everything; callers filter

**Temperature scaling:**
- T=1.0 everywhere in `temperature_scale.json` — intentional EMOS deployment (ae1d5ba).
  T-scaling is disabled; EMOS Gaussian path handles calibration. Do not flag.
- `_T_BELOW_PRIOR=3.0` and `_T_ABOVE_PRIOR=6.0` in `ml_bias.py` — fallback priors
  that only apply when T is `None`, not when T=1.0. Do not flag.

**Dormant features (below activation threshold — do not flag as dead code):**
- `order_executor._sameday_effective_cap()` — dormant until 150 same-day settled
  trades (~99 currently). Do not recommend removal.
- `BELOW_GATE_ENABLED` not set — dormant until 30 settled below-condition trades
  (~16 currently). Correct.
- `SAME_DAY_RESERVE_SLOTS` not set — dormant. Correct.

**Ensemble pin directional accuracy:**
- `cron.py` fetches `multiday_directional_accuracy` (not raw `directional_accuracy`)
  from `get_edge_realization_rate()`. This IS filtered for multi-day trades. Do not
  flag as same-day contamination — the filter is correct.

**WinError 32 in safe_io.py:**
- Windows Defender scans the temp file before rename, causing WinError 32. The retry
  on attempts 2/3 is intentional and self-healing. Do not flag.

**Reporting vs trading balance:**
- `paper.get_max_drawdown_pct()` reads `get_balance()` directly. Intentional — it is a
  reporting metric, not a trading gate. Do not flag under I8.

**NWS sigma ladder asymmetry at days_out=1:**
- `days_out=1 + between` → sigma=1.0; `days_out=1 + above/below` → sigma=2.0.
  This asymmetry is deliberate engineering that fixes a 38.4% probability cap issue
  for between-condition markets. Do not flag as inconsistent.

**Graduation gate Brier threshold:**
- The actual gate in `paper.graduation_check()` uses `≤0.23` (last-50 multi-day
  trades). Some display code in `main.py` may still show `< 0.20` — that is stale
  display code. Do not flag the gate as wrong; flag stale display code as LOW/INFO.

---

## Confidence Levels

Every finding must carry a confidence level:

- **Confirmed** — you traced the exact code path and verified the bug fires on a
  plausible input
- **Likely** — strong structural evidence but you could not fully trace all paths
- **Possible** — suspicious pattern that could be intentional; argue both sides

An UNCERTAIN verdict (could be intentional) does not get a FIX. It gets an explanation
of both interpretations.

---

## Output Format

### TIER 1 function:
```
[FILE] fn() L:NNN–NNN  ★ T1
Score: N/10  |  Confidence: Confirmed / Likely / Possible
AC: ALL PASS  –or–  FAIL AC#N — "exact quote from the code"  –or–  N/A
Red flag: NONE  –or–  RF# — "exact quote from the code"
Invariants: list only applicable ones — I# PASS / FAIL (one-line reason if FAIL)
STRENGTHS:
• ...
WEAKNESSES:
• line NNN: <what is wrong and why it matters>
FAILURE SCENARIO (required if score ≤7):
<exact conditions: what input, what code path, what breaks and when>
FIX (required if score ≤6):
file.py:NNN — replace `old` with `new`
VERDICT: keep as-is / fix before live / rework
```

### TIER 2 function:
```
[FILE] fn() L:NNN  N/10 — <one sentence>  [Confidence: C/L/P]
FIX: file.py:NNN — <exact change>  (omit if score ≥7)
FAILURE SCENARIO: <exact conditions>  (required if score ≤4)
```

### Dead code / dormant feature:
```
[FILE] fn() L:NNN — DORMANT (intentional / suspected dead code)
<one sentence on why it appears dormant and whether removal is safe>
```

### Red flag override:
If a TIER 2 function fires any red flag (RF1–RF6), promote it to a full TIER 1 block.
