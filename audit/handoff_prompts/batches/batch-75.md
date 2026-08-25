# Batch 75: METAR-lock running extreme is persisted as a forecast — contaminates the live station-bias learner

## Context

Repo: weather1. Written 2026-08-25 against master `5202e2d6a6c9` — **re-verify current before starting**; every line number below was checked at that commit and this repo's files move constantly.

Source: `backlog.txt`, cited **by title, not line number** (`L`-numbers are line offsets and drifted twice during this batch's own authoring). Grep this title:

> `predictions.forecast_temp_f IS WRITTEN WITH AN INSTANTANEOUS METAR TEMPERATURE ON method='metar_lockout' ROWS`

**Read the live entry, not this summary.** The entry was filed at `70859041` and then **corrected at `5202e2d6`** — its first version said "NOT a live-money bug today (no production path consumes the corrupted values)", which is wrong. It is now Priority HIGH. The entry's title also still says "INSTANTANEOUS METAR TEMPERATURE", which this batch's own investigation refined — see "What the value actually is" below. The title is close enough to grep for; the diagnosis in it is what matters.

Found by batch-53's replay experiment (which the contamination silently destroyed on its first pass), then isolated by that replay's opus review.

## What the value actually is — read this before touching anything

The earlier framing ("an instantaneous METAR reading is stored as a forecast") is *nearly* right and **the mechanism it names is wrong**, which matters because it points at the wrong fix.

`metar_lockout["comp_temp_f"]` is the **running daily extreme at lock time** — the day's max-so-far for a HIGH market, min-so-far for a LOW market. The code says so itself at `weather_markets.py:12620`:

```
f"HIGH market: running max {_comp_temp:.1f}°F not yet confirmed above
 threshold+margin — day's peak may still be ahead"
```

It is set at `weather_markets.py:12630` (above/below) and `:12906` (between), with `:12917`'s `setdefault` falling back to the instantaneous reading **only** when neither branch ran, and `:12443` setting both keys on a `locked=False` early return that no caller reads.

So the running extreme is **exactly right for the lock decision** — it is a hard lower bound on the daily high, which is the whole basis for locking — and **exactly wrong as a forecast of the daily extreme**, because it is a bound, not an estimate. It is systematically below the eventual high and above the eventual low.

The repo already measured how far: the comment at `weather_markets.py:12599-12613` reports, over 22,799 real station-days, `P(running max still rises >= 3F after the stated local hour)` = **26.9% at 14:00, 4.4% at 16:00**, never below ~2.8% even at 21:00; the LOW side's mirror is **12.8% at 14:00, still 7.3% at 21:00**.

**Nothing in the lock logic is broken. The bug is entirely in what gets persisted and who reads it.** Do not "fix" `_metar_lock_in` or the margin logic.

## Measured impact (live `predictions.db`, 2026-08-25)

Settled rows joining `predictions` to `outcomes_valid` with both `forecast_temp_f` and `settled_temp_f`: 313 total — `ensemble` 208, `metar_lockout` 103, `normal_dist` 2. On D+0:

| method | var | n | mean `forecast_temp_f` | mean settled | bias | rmse |
|---|---|---|---|---|---|---|
| metar_lockout | max | 65 | 78.40 | 87.03 | **+8.632** | 10.907 |
| metar_lockout | min | 38 | 82.21 | 71.79 | **−10.421** | 11.686 |
| ensemble | max | 47 | 85.49 | 85.68 | +0.193 | 3.367 |
| ensemble | min | 28 | 70.15 | 71.71 | +1.567 | 2.462 |

The tell: on lockout rows the HIGH-market stored value (78.40) is **colder** than the LOW-market stored value (82.21). Impossible for daily extremes; exactly what running extremes captured at different times of day look like.

It is **not** self-correcting. Lockout bias by half-month (max markets): +8.60, +7.65, +14.52, +15.55 — flat to growing. What fell away is the *mix*: lockout share of settled D+0 rows ran 95%, 69%, 46%, 8%, 6%, 0% from 2026-06a to 2026-08b. The writer is unchanged.

## The live path (this is why it is HIGH, not Medium)

Verified at `5202e2d6a6c9`:

1. `weather_markets.py:14721` — `_metar_ct = metar_lockout.get("comp_temp_f", metar_lockout.get("current_temp_f"))`
2. `weather_markets.py:14723` — `forecast_temp = _metar_ct if _metar_ct is not None else (_fallback_temp or 0.0)`
3. `weather_markets.py:15219` — returned as `"forecast_temp"`
4. `trade_cycle.py:920` — persisted as `"forecast_temp_f": analysis.get("forecast_temp")`
5. `paper.py:1464` — `_score_ensemble_members(t, outcome_yes)` on every settled paper trade
6. `paper.py:1569` — `model_means["blended"] = trade.get("forecast_temp")` → `ensemble_member_scores` as `model='blended'`
7. `tracker.py:7377-7382` — `get_dynamic_station_bias` **prefers** `WHERE model = 'blended'`
8. `weather_markets.py:401` — `from tracker import get_dynamic_station_bias as _gdbs` → `_DYNAMIC_BIAS_CACHE` → applied to live forecasts

`paper.py`'s own comment at :1569 already states that `"blended"` is "preferred by `get_dynamic_station_bias()` over the per-model means". The original backlog entry read the right table (`ensemble_member_scores`, which is indeed not `predictions`) and drew the wrong conclusion — the contaminated value flows *into* that table.

**A second consumer, on a trade-entry safety gate:** `weather_markets.py:13766` uses the same `comp_temp_f`-then-`current_temp_f` fallback to compute `_yes_clearance`, the between-bucket station-gap margin. Trace it before deciding scope — a running extreme is arguably the *correct* input for a clearance check (it is the value that decided the lock), so this site may be fine as-is. Decide it explicitly rather than changing it by reflex.

## What is NOT established — do not assume it

**The magnitude of contamination actually sitting in `ensemble_member_scores` is unknown**, and the first attempt to measure it failed. That table has no `ticker` column — its schema is `id, city, model, predicted_temp, actual_temp, target_date, logged_at, var, implied_prob, brier` — so the only join key back to `predictions` is `(city, target_date, var)`, and it is unreliable: of 148 `model='blended'` rows matched that way, `actual_temp` equals `outcomes.settled_temp_f` **exactly on only 38**, with a max absolute difference of 30.8°F.

A first pass over that join suggested ~40% of blended rows trace to `metar_lockout` at +3.4°F bias — but the same join showed near-identical bias on supposedly-clean rows (max/lockout +3.836 vs max/no-lockout +3.635), which is evidence the join is mismatching rather than evidence of contamination. **Do not quote the 40% or the +3.4°F figure as a finding.** Establishing the real magnitude is part of this batch's work, not an input to it.

## Items

### 1. Stop the running extreme becoming a `"blended"` model score — the live half

`paper.py:1569` unconditionally treats `trade["forecast_temp"]` as a model forecast. On a lockout trade it is not one.

**Decision (ask):**
- **(a)** Skip the `"blended"` entry entirely when the trade's method is `metar_lockout`. Smallest change; `get_dynamic_station_bias` falls back to per-model means for those rows, which is its documented pre-`blended` behaviour.
- **(b)** Keep logging it under a distinct model key (e.g. `"metar_lock_extreme"`) so the sample survives for analysis but `get_dynamic_station_bias`'s `model = 'blended'` filter excludes it.

**Recommend (b).** It preserves the observation — which is real data, just not a forecast — and it makes the exclusion visible in the table rather than as an absence. (a) silently drops rows, which is how this class of bug hides.

Check whether `trade` carries `method` at that point; if not, that plumbing is part of the item.

### 2. Decide what `predictions.forecast_temp_f` means

**Decision (ask):**
- **(a)** Write `NULL` on lockout rows. Every existing consumer becomes correct with no query change. Loses the record of what the lock saw.
- **(b)** Add `observed_extreme_f` (or similar), move the value there, leave `forecast_temp_f` NULL on those rows. Preserves the audit trail; needs a migration.

**Recommend (b)**, and note this is a real recommendation rather than the cautious default: the value is a genuine observation with analytic use (it is the running extreme at decision time), and the failure mode here was precisely that a meaningful number sat in a column whose *name* misdescribed it. Renaming the destination fixes the category error instead of deleting the evidence.

Whichever is chosen, decide separately what to do with the **103 existing contaminated rows** — leave, NULL, or migrate. State the choice.

### 3. Make this measurable: add `ticker` to `ensemble_member_scores`

Without it, item 1's fix cannot be verified and the "how bad was it" question stays unanswerable. Follow the existing `ALTER TABLE` migration style in `tracker.py` (see the `predictions` column migrations around `tracker.py:106-353` for the established shape). Backfill where a unique `(city, target_date, var)` match exists; leave NULL where ambiguous rather than guessing.

### 4. Two places in the repo disagree about the cross-city-pooling correlation, and the stale optimistic one is in the registry

This item changed shape during authoring — the first draft framed it as "recompute `r` with a `method` filter". That is not the main problem. **Two in-repo sources already disagree about this number, and a future session deciding whether to wire the signal live would read the wrong one.**

- `weather_markets.py:8870-8876`, `_SignalRegistryEntry(key="cross_city_pooling")`, still advertises: *"Last check (2026-07-23): Pearson r~=0.35, but thin per-estimate coverage ... too sparse to trust yet."*
- `tests/test_dead_code_scan.py:285-305`, the allowlist entry for `tracker.get_regional_recent_bias`, records a **later and far more careful** result: the function was briefly wired into `weather_markets._get_combined_station_bias()` on 2026-08-22, an opus review caught a contamination path (a correlated city with a thin static-bias entry leaking its persistent residual into a neighbour), it was fixed at the source, and re-running the validation **against the fixed version** gave **r=0.08 (n=35, was 109), sign agreement 51% — a coin flip.** The wiring was reverted. The original r=0.38 was "substantially an artifact of that same contamination".

So the registry's `r~=0.35` is superseded by a post-fix `r=0.08` that says there is no signal. The registry is the surface a future session consults; the truth is buried in a test file's allowlist string.

**The work:** update the `correlation_note` to carry the 2026-08-22 post-fix result and its date, and point at the allowlist entry (or the backlog entry) for the reasoning. This is a docs/constant change, not an analysis — the analysis was already done correctly by someone else and simply never propagated.

**Secondary, and genuinely lower value than the first draft implied:** `get_regional_recent_bias` does select `predictions.forecast_temp_f` with no `method` filter, so the 2026-08-22 re-run inherited this batch's contamination too. Adding the filter is correct and cheap. But do not sell it as likely to rescue the signal — it starts from r=0.08 on n=35, and the honest prior is that a method filter shrinks n further rather than revealing anything.

`get_regional_recent_bias` has **no production call site** (tests only). Nothing here is urgent; it is on this batch because it is the same contamination and the same file, and because a stale optimistic number sitting in a decision surface is exactly how a bad wiring decision gets made later. Same discipline as `feedback_reverify_correlation_after_contamination_fix`.

## Sequencing / conflicts

- Independent of batches 63-74. Touches `paper.py`, `tracker.py`, `weather_markets.py`, `trade_cycle.py` — check 63's `trade_cycle.py`/`weather_markets.py` items and 60's `main.py` work for in-flight overlap before starting.
- Item 3's migration touches the same `tracker.py` migration list many batches append to. Re-run `git fetch` immediately before committing.

## Process

**Items 1 and 2 open with `AskUserQuestion` — ask both together, before writing code.** Keep each question terse; push the trade-offs into the option descriptions.

**Full 29-step ceremony, opus review at `effort: high`.** This is a bias path feeding live forecast adjustment — it clears the LOW-tier bar on every axis (multi-file, multi-subsystem, live-money-adjacent, plus a schema migration).

Tests: `tests/test_paper.py`, `tests/test_tracker*.py`, whatever covers `_score_ensemble_members` and `get_dynamic_station_bias`, plus a new regression test that a `metar_lockout` trade does **not** produce a `model='blended'` score row. **Never run the bare full suite.**

That new test asserts an absence, so per workflow step 28 it **must** carry a positive control in the same test — assert that a non-lockout trade in the same fixture *does* produce the `blended` row. Without it, a later change that drops the trade earlier in the pipeline makes the test pass vacuously.

Isolate any scratch/verification script the way a pytest fixture would (`safe_io.project_root` / `tracker.DB_PATH` redirected to a temp copy) — this repo has a documented history of scratch scripts writing into the real `data/`, and batch-53's own replay only avoided it by doing this.

Lint via the real pre-commit hook. Update the backlog entry with the decisions and their reasoning, run `python backlog_index.py`, re-open the regenerated `BACKLOG_OPEN.md` to confirm the entry landed where expected, and **confirm with the user before committing**.
