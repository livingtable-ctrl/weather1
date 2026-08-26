# Batch 78: observability and retention — three things the operator cannot currently see

## Context

Repo: weather1. Written 2026-08-26 against master `f5cbbf70` — **re-verify current before starting**. Live trading dormant. All three items are observation/plumbing; none changes a trading decision.

**Files owned: `tracker.py`, `cron.py`, `trade_cycle.py`, `kalshi_ws.py`.**
**Read-only here (owned by other batches): `web_app.py` (batch 79), `weather_markets.py` (batch 76).** Item 2 references `batch_prewarm_ensemble` as the volume driver and item 3 has a `web_app.py` caller — read both, change neither.

Source: three `backlog.txt` entries, cited by title:
- `NOTHING RECORDS PER-DAY THAT A SCAN RAN, SO AN OUTAGE AND A FULLY-GATED DAY ARE INDISTINGUISHABLE`
- `BATCH-64'S TWO FORWARD-ONLY TABLES HAVE NO RETENTION SWEEP, AND ONE OF THEM GROWS ~50x FASTER THAN ITS OWN MIGRATION COMMENT ESTIMATED`
- `BRIER_SKILL_SCORE() HAS NO CONDITION_TYPE FILTER`

## Items

### 1. [MEDIUM] An outage and a fully-gated day look identical

**Files:** `tracker.py` (`get_scan_activity`, `analysis_attempts`), `trade_cycle.py` (~`:566` the `if not analysis` branch; ~`:612` `all_results`), `cron.py` (~`:2389` `batch_log_analysis_attempts`).

Nothing records per-day that a scan actually ran. The A12 funnel panel's own docstring claims a distinction the data cannot make. No trading behaviour is affected, but this is the difference between *"the cron job is dead"* and *"the model had nothing to say"*, and the operator-facing panel cannot tell them apart.

**This is not hypothetical and the batch exists partly because of it.** batch-64 landed 2026-08-25 08:46 UTC and its four forward-only writers produced **nothing at all** until 00:30 UTC the next day, because no scan ran in between. That was invisible for a full day, and it caused a downstream session to conclude the writers were broken. A per-day scan record would have answered it in one query.

Design note worth deciding rather than assuming: a row saying "a scan ran" is cheap; a row saying "a scan ran and reached analysis for N markets" is the one that actually distinguishes the two states. Prefer the latter.

### 2. [MEDIUM] Two forward-only tables that only ever grow

**Files:** `tracker.py` (`ensemble_member_values` + `orderbook_depth_snapshots` migrations; `purge_old_predictions` as the sibling pattern), `kalshi_ws.py` (`_maybe_persist_depth`'s `DEPTH_SNAPSHOT_INTERVAL_SECS` throttle).

`purge_old_predictions()` covers `predictions` and `outcomes` only; a grep for `DELETE` against either new table finds nothing.

**The estimate in the migration comment was ~50× low, and the real number is now measurable rather than projected.** Measured 2026-08-26 after the first full scan: `ensemble_member_values` gained **597 real rows in one cron cycle** (20 cities × 5 models × 2 vars × target dates), member arrays of 17–50 values at ~0.3–1 KB each. `orderbook_depth_snapshots` is still **0** — it is written from the WS listener thread and needs live trading, so its growth is entirely unexercised and its retention window is a projection, not an observation.

`predictions.db` is already ~47 MB and `cloud_backup.backup_data` pushes it after every cron run, so unbounded growth is paid on every backup.

**`AskUserQuestion` for the window, per table — they are not the same question.** A15b's rank histogram is explicitly long-horizon ("needs months, not days"), so member values likely want keeping far longer than depth snapshots, which A4/A17 use for short-horizon replay. Do **not** pick a single number for both. Re-run the row counts before choosing; this figure has already been wrong once by 50×.

### 3. [LOW] `brier_skill_score()` has no `condition_type` filter

**Files:** `tracker.py` (`brier_skill_score`). `web_app.py` is its only non-test caller — **read-only in this batch**.

The query selects `p.our_prob` / `p.market_prob` / `o.settled_yes` with no exclusion at all, so a shadow-only rain/snow/hurricane/storm-order or `'between'` row can freely enter the calculation — the same contamination class the rest of the Brier family was fixed for in batch-06.

Note this is **not** a "will now disagree" case: it never had the hardcoded tuple batch-06 unified, it was always unfiltered. Use the module's existing `_condition_type_not_in_sql()` / `_excluded_brier_condition_types()` helpers rather than a fresh literal, and read `get_station_bias_by_lead`'s docstring first — it documents a deliberate exception where `'between'` is *kept*, and the reasoning there (a °F error is a valid sample for a between market even though its probability calibration differs) may or may not apply to a Brier skill score. Decide explicitly.

## Process — follow the 29-step implementation workflow in full

Items 1 and 2 are additive plumbing; item 3 changes a displayed statistic. LOW-tier downgrade does **not** apply — this spans four files.

(1) Re-verify all three against live code, and **re-run the row counts for item 2 rather than quoting the figures above** — they are hours old and this number has already been wrong by 50×. (3) `AskUserQuestion` for item 2's per-table windows and item 3's `'between'` question. (7) Mutation-tested tests via **Edit**-revert; item 3's test should pin that a shadow-family row is excluded, with a positive control proving a real row still counts. (8) Scoped: `tests/test_tracker.py`, `tests/test_cron*.py`, `tests/test_trade_cycle_engine.py`, `tests/test_kalshi_ws.py`. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push — `tracker.py`'s `_MIGRATIONS` list is append-only and shared; if item 2 adds one, re-number rather than hand-merging and re-run `init_db()` against an empty scratch DB to prove the chain still applies from zero. `_SCHEMA_VERSION` must equal the list length. (19) `python backlog_index.py`.

**Current schema is v76** (batch-75 added `observed_extreme_f` at v75 and `model_forecast_temp_f` at v76). Any migration this batch adds is v77.
