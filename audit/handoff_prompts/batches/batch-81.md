# Batch 81: the graduation floor is a coin flip, and the 6× accrual doesn't reach it

## Context

Repo: weather1. Written 2026-08-26 against master `6b116698` — **re-verify current before starting**.

> ## ✅ UNBLOCKED 2026-08-26. All five prerequisites landed.
>
> `703e2c86` (76), `aaf76d67` (77), `96ffc611` (78), `2af1daef` (79), `0b645aca` (80), plus `aa7c15ed`, `4bfa93f2` and `202be163` as follow-ups. **Re-anchor onto `0b645aca` or later.** Every one of this batch's five files was modified by that set, so treat all line numbers below as approximate and re-locate by symbol.
>
> **Re-verified against `0b645aca`:**
>
> | Claim | Status |
> |---|---|
> | Twelve `_SignalRegistryEntry` blocks, **ten** on `sample_floor=20`, two on `None` | holds — batch 76 did not change the count |
> | `floor_cleared = count >= entry.sample_floor` | moved `~:10388` → **`:10409`** |
> | `_notify_feature_activation` | moved `~:9900` → **`:9921`** |
> | `analysis_attempts` has no signal columns | **holds** — batch 78 added a per-day scan record but left this table's columns untouched: `ticker, city, condition, target_date, analyzed_at, forecast_prob, market_prob, days_out, was_traded, outcome, status, not_found_at, last_checked_at` |
>
> So **item 2 is fully intact** and is still the larger half of the batch. Batch 78's retention work chose 730 days for `ensemble_member_values` (`4bfa93f2`) — that is the window to coordinate with, not a number to re-litigate.

**Files owned (once unblocked): `weather_markets.py`, `main.py`, `tracker.py`, `cron.py`, `order_executor.py`.**

Source: `backlog.txt`, cited by title — `THE SIGNAL REGISTRY'S sample_floor=20 CLEARS AT ~27% STATISTICAL POWER -- IT CANNOT DISTINGUISH A REAL SIGNAL FROM NOISE`. Item 2 below is **new**, developed 2026-08-26, and is not in that entry.

## Correct the entry's own numbers first

Three claims in that entry are wrong, verified 2026-08-26 by enumerating `_SignalRegistryEntry` blocks in `weather_markets.py`:

| Entry claims | Actual |
|---|---|
| "Nine of the eleven registry entries use `sample_floor=20`" | **Ten of twelve** |
| `richer_ml_features` uses `sample_floor=20` | `sample_floor=None` |
| `rain_forecast_blend` uses `None` | **`sample_floor=20`** |

The ten on `sample_floor=20` are: `run_trend`, `market_implied`, `market_implied_rain`, `gated_edge`, `nbm_quantile_prob`, `ecmwf_consensus_gap`, `gem_graduation`, `ukmo_graduation`, `hrrr_graduation`, `rain_forecast_blend`. The two on `None` are `richer_ml_features` and `cross_city_pooling`. Fix the entry as part of this batch.

## Item 1 — raise the floor to ~86

**Files:** `weather_markets.py` (the ten `sample_floor=20` entries, `get_signal_graduation_report`'s `floor_cleared` at ~`:10388`, `_notify_feature_activation` at ~`:9900`), `main.py` (the report printer at ~`:7489`).

The floor's own problem, from the entry: at n=20–26 a binary-outcome signal cannot be distinguished from noise — ~27% power. Yet `get_signal_graduation_report` sets `floor_cleared = count >= entry.sample_floor`, `main.py:7490` prints `"{count}/{floor} -- floor cleared"` in **green**, and `_notify_feature_activation` fires an alert saying the signal is "ready for the correlation check". Six signals have now crossed that bar.

**Derive the replacement rather than picking one.** Back-solving from the entry's own "n=20 → ~27% power" gives a per-observation effect of **0.3012**, hence:

| Power | n |
|---|---|
| 50% | 42 |
| **80%** | **86** |
| 90% | 116 |

86 is the defensible default (two-sided 95%, 80% power — the same convention `audit/DATA_ACCRUAL_PLAN.md` and the `analysis_attempts` entry already use, so the repo stays internally consistent). **Re-derive it yourself and check the arithmetic before trusting this table**; if the effect size you back-solve differs, the number moves.

**Measured cost of raising to 86, as of 2026-08-26** — three of five are already there or days away:

| Signal | Have | Rate/day | Days to 86 |
|---|---|---|---|
| `gated_edge` | 110 | 10.33 | already clear |
| `implied_mean` | 82 | 2.73 | 2 |
| `ecmwf_consensus_gap` | 77 | 2.57 | 4 |
| `run_trend_delta` | 40 | 1.13 | 41 |
| `nbm_quantile_prob` | 27 | 0.87 | 68 |

Note the ordering flip that motivates the whole batch: **`nbm_quantile_prob` is the signal that cleared the floor and fired the activation alert, and it is the furthest from being measurable.** It looked ready precisely because the bar was wrong.

**`AskUserQuestion`:** the replacement number, and one-floor-vs-two. A single 86 is simplest. A two-tier design (a low "worth looking at" bar and a high "safe to wire live" bar) preserves the early visibility the current floor gives without letting it read as a graduation signal — but it is more machinery. Ask; do not pick.

## Item 2 — the 6× accrual bypasses these floors entirely

**Files:** `tracker.py` (`analysis_attempts` schema, `log_analysis_attempt` ~`:12766`, `batch_log_analysis_attempts` ~`:12821`), `cron.py` and `order_executor.py` (its callers).

On 2026-08-26 the `analysis_attempts` settlement sweep took scored rows from **115 to 584** — a 5.1× increase, and the unbiased population (minimum |forecast − market| = 0.0011, with 138 rows below the 0.08 edge floor, where `predictions` structurally contains none below 0.0984).

**None of that reaches the signal floors.** `analysis_attempts` columns are:

```
ticker, city, condition, target_date, analyzed_at, forecast_prob,
market_prob, days_out, was_traded, outcome, status, not_found_at,
last_checked_at
```

No signal values. Every registry floor counts `predictions` rows carrying the signal column — the selection-biased population written after placement. That is why the two laggards accrue at 0.87 and 1.13/day while the unbiased population accrues at ~22/day.

**If signal values were also logged onto `analysis_attempts`, any signal would reach 86 rows in ~4 days instead of 1–2 months — and those rows would be unbiased.** That converts signal graduation from a quarterly question to a weekly one, permanently, and it is the larger half of this batch's value.

**`AskUserQuestion` before implementing:** which signals to log, and in what shape. Options include a `signal_values` JSON blob (mirrors `predictions.signal_values`, one column, no migration per signal) versus typed columns (queryable directly, but a migration each). Note `analysis_attempts` currently holds ~709 rows and is written on every analysed market, so the volume question from batch-78's retention item applies here too — coordinate with whatever window that batch chose.

**Do not conflate the two populations when reporting.** A registry count that silently mixes biased `predictions` rows with unbiased `analysis_attempts` rows would be worse than either alone. If both feed a floor, the report must say which is which — that ambiguity is the same class of defect batch-75 spent a session removing from `forecast_temp_f`.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) in full

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`. Full ceremony, no downgrade: five files, two subsystems, and item 1 changes a surface an operator acts on.

(1) Re-verify everything — **including the tables above**, which are hours old at time of writing and describe accrual rates that change daily. Re-run the counts and re-derive the power arithmetic; do not inherit either. Also re-check the twelve registry entries, since batch 76 may have touched `weather_markets.py`. (3) `AskUserQuestion` for both items' decisions; they are independent and can be asked together. (7) Mutation-tested tests via **Edit**-revert. Item 1's test must pin that a signal below the new floor does **not** report `floor_cleared` and does **not** fire `_notify_feature_activation` — an absence assertion, so pair it with a positive control that a signal above the floor does both. (8) Scoped: `tests/test_weather_markets.py`, `tests/test_tracker.py`, `tests/test_cron*.py`, plus whatever covers the graduation report. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`, and correct the entry's three wrong numbers while you are in it.

**One framing worth keeping.** Raising a floor looks like slowing yourself down. It is the opposite here: the floor's job is to stop a noise signal being wired into live pricing, and at n=20 it cannot do that job at all. Three of the five signals clear 86 today or within a week, so most of the "cost" is already paid — and item 2 removes most of what remains.
