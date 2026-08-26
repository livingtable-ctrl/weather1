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

## C. There is no real queue — CORRECTED 2026-08-26

**An earlier revision of this section listed five entries as "the real queue, ordered by value". That was wrong, and the way it was wrong is the point.** Those five were classified from entry *titles* and from inference about which files they touch. Reading each entry's own *Still open* text instead shows that **none of them is startable today.** Every one is data-gated, deliberately deferred, or already shipped.

Verified entry by entry, with the gates re-measured against the live DB rather than quoted:

| Entry | What its own text says is left | Gate, measured today |
|---|---|---|
| Rain monthly day-specific (L6064) | Both halves **shipped** — near-term ≤16-day ensemble signal 2026-07-28, >16-day far-tail blend 2026-08-17. Left: the graduation decision only. | **17 of 20** settled rain predictions. The entry still says "6 of the 20" — stale, and it is close to clearing. |
| Run-to-run trend (L12827) | "data-collection phase, not an active development item" | **28 of 60** rows (`run_trend_delta IS NOT NULL AND settled_temp_f IS NOT NULL`). Entry says 24 as of 2026-08-22 → ~1/day → **~32 days out**. Its second gate (does positive delta correlate with settling above forecast) has never been run either. |
| Richer ML features (L12989) | "retraining/feature-vector wiring still gated on accumulation, as this entry's own *when to revisit* always said" | re-verified 2026-08-22: "not yet actionable given the per-city sample" |
| Rain/snow/hurricane surface (L9533) | Rain Step 1+2, St. Petersburg onboarding, Snow Step 1+2 **all shipped**; three hurricane sub-models shipped since. Genuinely open: **KXHURCAT and per-city landfall have no model at all.** | Not "finishing" work — that is two new shadow models, greenfield, at Low priority. |
| Far-tail rain dry-tilt (L26622) | "scope narrowed, fix **deliberately deferred** to graduation" (batch-62 item 6) | Do not widen it back without a reason. |

**Two stale counts worth correcting in `backlog.txt` while nearby:** L6064 says 6 of 20 and is actually 17 of 20; L12827 says 24 and is actually 28.

### So the complete answer to "what is achievable now"

**Nothing in this set.** Of the 15:

- **2 should be closed** — EMOS and cross-city pooling (section A). Evidence in hand, no code.
- **1 is already in flight** — fixture latency, inside batch 83.
- **2 are deliberate deferrals** — `/api/trades` and far-tail dry-tilt. Someone decided; leave them.
- **9 are data-gated**, none clearing today. Nearest is rain graduation at 17/20.
- **1 is greenfield** at Low priority — the two missing hurricane models.

The soonest thing to become real is the **rain monthly graduation decision at 17/20**. Watch that one; three more settled rain predictions and it is a genuine, well-scoped piece of work with both halves of its implementation already shipped.

### Why the earlier revision got this wrong

It classified by title and by inferred file set, and never read what each entry said was left. This repo's backlog titles describe the *original* problem, not the residual — an entry titled "MONTHLY MODEL HAS NO DAY-SPECIFIC FORECAST SIGNAL" now has that signal, twice over, and is waiting on twenty settlements. Any triage pass over this file has to read the `[PARTIALLY RESOLVED ...]` bracket and the trailing status lines, not the headline.

## D. Free right now, but deliberately deferred

`web_app.py`'s `/api/trades` double-load (L26156) — `paper.py`, `web_app.py`, LOW. The only entry here that collides with nothing. But batch 61 narrowed it and left the remainder open **on purpose**, and what remains is a caching-strategy decision rather than a fix. Batching it would invite someone to implement past a deliberate deferral. Left alone on purpose.

## The lesson worth keeping

Parallel batching worked for 76–86 because those were *adjacency findings* — small defects spotted at the edges of other work, naturally scattered across the codebase. The partially-resolved set is the opposite: each entry is a half-finished feature, and features in this repo are built in `weather_markets.py`. **A backlog's parallelisability is a property of how its items were discovered, not of how many there are.** Check the file-overlap matrix before promising a batch set.
