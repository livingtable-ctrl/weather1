# Batch 64: Forward-only data writers — start the sample clocks (DO FIRST)

## Context

Repo: weather1 (Kalshi weather-trading bot). Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading is dormant (`LIVE_TRADING_ENABLED` unset). Nothing in this batch changes a trading decision: every item is a **write-only observation** added alongside existing behaviour.

Source: the Weather V3 additions design handoff (panels A3, A4, A15, A17, A18), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md) for the full set and the parallel-track map.

**Why this batch is first, and it is not a dependency argument.** These four writers collect data that **cannot be backfilled**. The design handoff says it outright for A15: "it is forward-only — you cannot backfill it. Start writing members the day you start this panel." Batches 70 and 71 consume all four. Every day this batch is not running is a day permanently absent from those panels' samples. The code is small; the value decays with delay.

Files owned by this batch: `order_executor.py` (`_current_forecast_cycle` only), `kalshi_ws.py`, `paper.py`, `tracker.py` (**migrations + writers only** — no query functions; those belong to batches 65-67), and the forecast-fetch call sites in `weather_markets.py`.

**Coordination:** `tracker.py`'s `_MIGRATIONS` is a single ordered array and batch 72 also appends to it. If both are in flight, the second to land **rebases and re-numbers** rather than hand-merging conflict markers, bumps `_SCHEMA_VERSION` to match the list length, and re-runs `init_db()` against an empty scratch DB to prove the chain still applies from scratch. Batch 73 also touches `order_executor.py`, ~3,000 lines from item 1's region — 73 rebases onto this batch, not the reverse.

## Items

### 1. W1 [HIGH]: `forecast_cycle` records a wall-clock guess, not the model run it came from

**Files:** `order_executor.py` — `_current_forecast_cycle()`; call sites via `_build_log_prediction_kwargs`; the forecast-fetch layer in `weather_markets.py`.

```python
def _current_forecast_cycle() -> str:
    now = datetime.now(UTC)
    cycle_hour = 12 if now.hour >= 12 else 0
    return f"{now.strftime('%Y-%m-%d')}_{cycle_hour:02d}z"
```

This infers the cycle from the current hour rather than reading the run timestamp of the product actually fetched. A scan at 11:58 UTC that consumed the 06z run records `00z`; a scan at 12:02 consuming the same 06z data records `12z`. The stored value is therefore **not** a model-run identifier, and A18 — whose entire question is "are we faster than the market at pricing a new cycle" — cannot be built on it. The design handoff's claim that three of A18's four timestamps already exist is wrong in exactly this way.

Note the existing value is not useless: it is a genuine dedup key for "orders within the same wall-clock half-day", which is what `#37` originally wanted. **Do not repurpose or delete it** — orders dedup on it today.

**Fix direction:** add a **new** field carrying the fetched product's own run/init timestamp (Open-Meteo and NBM both return one; find where the response is parsed and thread it through rather than re-requesting). Persist it alongside `forecast_cycle`, do not replace it. Keep it log-only this batch — nothing reads it until batch 71.

### 2. W2 [HIGH]: per-member ensemble values are never persisted, only the blend

**Files:** `weather_markets.py` (wherever ensemble member values exist before collapsing to mean/σ), `tracker.py` (migration + writer), `paper.py` (`_score_ensemble_members` for the sibling pattern).

`n_members` is stored on each prediction and `ensemble_member_scores` exists (schema v34-v36, with `var`, `implied_prob`, `brier`) — but that table is per-**model** (icon vs gfs vs ecmwf), one row per city/model/target_date. The individual member values within an ensemble are discarded once mean and σ are computed.

A15's rank histogram needs the full member distribution per forecast: where the observed value falls among the sorted members is the entire diagnostic. CRPS in the truncated-normal case needs the same. Neither can be computed from mean and σ alone, and neither can be reconstructed after the fact.

**Fix direction:** persist member values per (city, target_date, model, cycle) at the point they are already in memory. Storage shape is a real decision — a JSON array column on the existing prediction row versus a separate normalised table — surface it via `AskUserQuestion` with a recommendation; the volume (members × cities × cycles × days) is the deciding factor and should be estimated from live counts, not guessed. Write-only this batch.

### 3. W3 [MEDIUM]: no per-cycle forecast history row exists

**Files:** `tracker.py` (migration + writer), `weather_markets.py` (blend step).

A3 needs one row per cycle per city — source name, cycle timestamp, blend weight, value, and the reason a stale source was excluded — and A7's timeline needs the same rows for its middle section. Today `blend_sources` (model weights, JSON) and `run_trend_points` are persisted per prediction, and `get_forecast_run_trend()` reconstructs a movement series from prior predictions — so this is **partly** covered already, contrary to the handoff's "the only genuinely new forecast pipeline".

What is missing is the per-source detail at blend time: which sources were considered, which were excluded for staleness and why. That exclusion decision currently surfaces only in logs.

**Fix direction:** re-read `get_forecast_run_trend()` and `blend_sources` first and scope this to the genuine gap — do not build a parallel history table that duplicates what those already reconstruct. The staleness-exclusion reason is the part with no persistent home.

### 4. W4 [MEDIUM]: order-book depth arrives over the websocket and is thrown away

**Files:** `kalshi_ws.py` — `update_orderbook_cache`, `get_cached_book`, and the `orderbook_delta` branch of the message parser.

`get_cached_book()` says so directly:

> This is top-of-book only (best bid/ask from ticker ticks), not full depth — orderbook_delta messages are stored but not applied to a usable depth structure.

The deltas are already being received and stored. A4's ladder, its edge-as-you-fill walk, and A17's counterfactual replay all need depth applied to a real book structure and snapshotted.

The docstring's reasoning for the current state is sound and should be preserved: "this bot's order sizes don't require walking multiple depth levels" is true for the reprice/chase path. Adding depth must not change what that path reads.

**Fix direction:** apply deltas to a proper book structure and snapshot it periodically. Leave `get_cached_book()`'s return shape **unchanged** so no existing caller's behaviour moves — add a new accessor for depth. Note `kalshi_client.get_orderbook()` already exists for on-demand fetches and is the correct fallback when the WS cache is cold or stale.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps, no LOW-tier downgrade: this batch spans four files and two subsystems, and item 1 touches a field that live order dedup reads.

(1) Re-verify every claim above against live code — particularly item 3, where `get_forecast_run_trend()` may already cover more than this transcription assumes; scope the item down if so rather than building a duplicate. (3) Items 2 and 3 both have genuine storage-shape decisions (JSON column vs normalised table; extend existing vs new table) — surface both via `AskUserQuestion` with real recommendations and an estimate of row volume from live data, not a guess. Give them equal visibility; do not decide one in a code comment. (7) Real, mutation-tested tests via Edit-revert, not string-replace scripts. For item 1 specifically: a test asserting the new field carries the **product's** timestamp needs a mock whose run time deliberately disagrees with the wall clock, or it proves nothing. For item 4, pair any absence-assertion with a positive control. (8) Scoped tests only — `tests/test_tracker.py`, `tests/test_kalshi_ws.py`, `tests/test_paper.py`, `tests/test_order_executor.py`, plus whatever covers the forecast-fetch layer. **Never the full suite.** (9) Lint via the real pre-commit hook, not the repo `.venv` mypy. (10/19) Backlog entries + `python backlog_index.py` if `backlog.txt` is touched — note other sessions are actively restructuring `backlog.txt` into batches, so rebase before editing it and re-check your entry landed. (11) Independent opus review at `effort: high` before push; review the fixes to its findings too. (14) Compressed-pointer memory update before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase-if-diverged immediately before the actual push, not just at session start.

**Verification that matters more than the tests here:** after landing, confirm each writer is actually producing rows in the live DB within one cron cycle. A forward-only writer that silently no-ops costs exactly what this batch exists to prevent. Check row counts the next day, not just that the code path executes.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
