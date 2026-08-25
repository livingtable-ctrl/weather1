# Batch 67: A11 exit policy + A16 strike ladder — both on data that already exists

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Both items are read-only analytics; neither changes an exit or sizing decision.

Source: Weather V3 additions handoff (A11, A16), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `tracker.py` (new query functions), `web_app.py` (new endpoints), `weather_markets.py` (CDF-evaluation region only, item 2). Additive-only; rebase behind whichever of batches 64-67 lands first. No migrations here.

**The handoff is wrong about A11's dependency.** It says A11 needs "the stored mid-price series from A4" and places it after A4 in the build order. It does not: `price_history` (schema v37, `tracker.py:188`) already stores per-ticker OHLC candlesticks with `yes_bid_close`/`yes_ask_close` at 1-minute resolution, fetched from Kalshi's candlestick endpoint and backfilled across each market's **entire life** at settlement (`tracker.py:6101`, `backfill_price_history`). A11 is retrospective analysis over settled trades, so this is exactly the series it wants — and finer than the "at least hourly" the handoff asks for. **Verify this yourself before building** (`SELECT COUNT(*), COUNT(DISTINCT ticker) FROM price_history`); if coverage is thin for recent tickers, that is the real blocker, not A4.

## Items

### 1. A11 [MEDIUM]: one exit policy, never measured against any alternative

**Files:** `tracker.py` (new query function reading `price_history` + settled trades), `web_app.py`.

Every position is held to settlement. Nothing has ever compared that against exiting earlier, so "hold to settlement" is a default rather than a decision.

**Fix direction:** average P&L by exit timing (−48h, −24h, −12h, −6h, −2h, settle) across settled trades, reconstructing the price at each offset from `price_history`. Alongside it, a candidate-exit-rules table carrying **standard deviation as well as mean** — the handoff is explicit that the point of that column is that a rule can be worth taking for variance reduction alone, so do not drop it in favour of a single ranked number.

**Two things the handoff insists on, and they are the acceptance criteria:**
- The conclusion must be allowed to say **"no rule beats holding"**. Do not build a payload that presumes a change is warranted.
- Report `n` per bucket. A "best exit time" chosen from six buckets on a few dozen settled trades is a selection artifact; apply the same significance discipline A14 uses (`_paired_advantage` in `tracker.py`) rather than ranking raw means.

Machinery here is shared with A8 (batch 73's replay harness) — build the reconstruction so it can be reused rather than duplicated.

### 2. A16 [MEDIUM]: the scanner flags one strike and never sees the ladder it belongs to

**Files:** `weather_markets.py` (model-CDF evaluation), `tracker.py`/`web_app.py` for the payload.

Signals are listed flat. The model already produces a distribution per city-day, but it is evaluated at a single strike — so a better strike sitting next to the flagged one is invisible, and a market ladder that disagrees with the model's own shape is undetectable.

**Fix direction:** group the existing signals cache by city and target date instead of listing rows flat, and evaluate the model CDF at **every** strike in the group rather than one. Payload: per-strike model probability, market-implied probability, edge, and depth; the best opportunity and any strike where the market beats the model; and a ladder-inconsistency read describing where the market's ladder shape disagrees with the model's, with the two legs and the net cost of the spread.

**Scope discipline:** spread *execution* is a separate and much larger step. The handoff is explicit that the view is worth having even if only the single best leg is ever taken. Build the view; do not build multi-leg order placement.

Note the ladder-inconsistency figure needs care in its framing: a level error in the forecast partly cancels across legs, so a raw two-leg edge overstates the opportunity. Say so in the payload's own definition rather than leaving the consumer to infer it.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps. Both items span `tracker.py` and `web_app.py`, and item 2 touches the scan-path's model evaluation.

(1) Re-verify `price_history` coverage against the live DB **before** designing item 1 — the whole batch's premise rests on it. (3) `AskUserQuestion` for item 1's exit-offset set (the handoff's six are illustrative, not measured) and item 2's grouping key (city+target_date vs city+target_date+var — the `var` field matters for hourly/directional tickers). (7) Real, mutation-tested tests via Edit-revert. Hand-compute expected values in the test's own comments; pair every absence-assertion with a positive control — `tests/test_model_vs_market_brier.py` is the reference. For item 1, a test that reconstructs a known price at a known offset from synthetic `price_history` rows proves the reconstruction; asserting only that "a number came back" proves nothing. (8) Scoped: `tests/test_tracker.py`, `tests/test_weather_markets.py`, `tests/test_web_app.py`. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding, including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
