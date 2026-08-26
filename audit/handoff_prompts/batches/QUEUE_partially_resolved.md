# The 15 `[PARTIALLY RESOLVED]` entries — why they are a queue, not a batch set

Written 2026-08-26 against master `09e86a32`. This exists because "batch the remaining partially-resolved entries" turns out not to be possible, and the reason is worth recording rather than rediscovering.

## The structural finding

Batches 76–86 could run in parallel because no two shared a file. That property does not hold here. Counting how many of the 15 entries mention each source file:

| File | Entries |
|---|---|
| `weather_markets.py` | **11 / 15** |
| `main.py` | **9 / 15** |
| `tracker.py` | **8 / 15** |
| `ml_bias.py` | 4 / 15 |
| `paper.py`, `backtest.py`, `conftest.py` | 3 each |

Three hub files carry almost everything. **Every one of the twelve entries without an explicit `Files:` line is blocked by batch 82 alone** (which owns `calibration.py`, `weather_markets.py`, `ml_bias.py`, `main.py`, `tracker.py`). Of the three that do list files: one is blocked by 82, one is already inside batch 83, and one is free.

So there is no conflict-free partition. Attempting one would produce batches that collide with each other the moment two of them ran. What follows is a queue, ordered, with the entries that should not be worked at all separated out first.

## A. Close these — the evidence already exists, no code required

**EMOS calibration go-live** (`backlog.txt` L5306). The 40-row data floor cleared long ago — 136 settled `ens_var` rows against a floor of 40. But the fit fails its own held-out test, measured 2026-08-26 via `py main.py emos-train` (dry run, writes nothing):

```
Stage 1 (mean)     a = -1.1923   b = 1.0281
Stage 2 (variance) c =  2.0358   d = 0.4494
Training CRPS (120 rows) 1.5457
Held-out CRPS  (12 rows) new = 2.4096   baseline (raw ensemble) = 1.9794
  -> does NOT beat the raw-ensemble baseline
```

22% worse than raw ensemble out-of-sample, and 1.5457 → 2.4096 train-to-holdout is overfitting on 48 training rows. Note what it loses to: not T-scaling, the *raw ensemble*. **Close as decided-against**, record the numbers, and set a revisit trigger on the `ens_var` population being materially larger — 48 rows was always thin for a four-parameter fit. The confirmation gate built for this (`emos-train --activate`, `emos-status`, `emos-deactivate`) stays; it is what made this measurable safely.

**Cross-city recent-error pooling** (L15840). Already answered in code. `weather_markets.py`'s `cross_city_pooling` registry note carries the post-contamination-fix measurement — Pearson **r = 0.08 (n=35)**, sign agreement 51% — and ends *"Do not wire this live."* The r≈0.35 that originally justified it was substantially an artifact of the contamination the fix removed. **Close as won't-do-now**, with the measurement and a re-run trigger when more correlated cities' dynamic bias matures.

## B. Do not schedule — blocked on data or on an explicit decision already taken

| Entry | Blocked on |
|---|---|
| Rain arbitrage-check graduation (L10593) | real history; deferred by design |
| 3-way `model_consensus` item 2 (L11134) | explicit user deferral, 2026-07-23 |
| Sigma covariates (L15782) | re-verified 2026-08-22 as "no action possible" |
| GEM/UKMO graduation (L13393) | **superseded by batch 81.** Its recorded "min_n=20 cleared (36 obs)" is void: the floor is now ~112 and both models sit at 42, accruing ~2.3/day with no `analysis_attempts` counterpart to accelerate them. ~30 days out. |
| Public trades REST backfill (L15456) | capture shipped; the analysis passes are deferred behind the candlestick work |
| `market_lifecycle_v2` (L15972) | structurally blocked behind the fill-channel work |

Revisit these on their own triggers. None is work that can be started today.

## C. The real queue — sequential, because they all pass through `weather_markets.py`

Ordered by value, all blocked until batch 82 lands:

1. **Rain monthly model has no day-specific forecast signal** (L6064) — MEDIUM. Real modelling work behind the `RAIN_TRADING_ENABLED` shadow gate. The largest genuine item here.
2. **Rain / snow / hurricane category surface** (L9533) — MEDIUM for rain and snow. Includes a deferred `_parse_market_condition()` bug the entry says is still not fixed; confirm that independently before scoping.
3. **Richer ML calibration features** (L12989) — MEDIUM. Unchanged since original scoping; `feature_importance.py` is the one non-hub file it touches.
4. **Forecast run-to-run trend signal** (L12827) — logging half shipped, wiring half open. Now LOW, and note batch 81 re-floored `run_trend` to the new threshold, so re-check its sample position first.
5. **Far-tail rain dry-tilt floor-clip** (L26622) — INFO. Batch 62 narrowed the scope and deliberately deferred the fix to graduation; do not widen it back without a reason.

## D. Free right now, but deliberately deferred

`web_app.py`'s `/api/trades` double-load (L26156) — `paper.py`, `web_app.py`, LOW. The only entry here that collides with nothing. But batch 61 narrowed it and left the remainder open **on purpose**, and what remains is a caching-strategy decision rather than a fix. Batching it would invite someone to implement past a deliberate deferral. Left alone on purpose.

## The lesson worth keeping

Parallel batching worked for 76–86 because those were *adjacency findings* — small defects spotted at the edges of other work, naturally scattered across the codebase. The partially-resolved set is the opposite: each entry is a half-finished feature, and features in this repo are built in `weather_markets.py`. **A backlog's parallelisability is a property of how its items were discovered, not of how many there are.** Check the file-overlap matrix before promising a batch set.
