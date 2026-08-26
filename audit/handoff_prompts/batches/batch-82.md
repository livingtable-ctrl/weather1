# Batch 82: fit same-day blend weights separately — completing the original design

## Context

Repo: weather1. Written 2026-08-26 against master `c9cd4426` — **re-verify current before starting**.

> ## ✅ UNBLOCKED 2026-08-26. All three prerequisites landed.
>
> `703e2c86` (76), `96ffc611` (78), `2af1daef` (79). **Re-anchor onto `0b645aca` or later.**
>
> **Re-verified against `0b645aca` — the batch's two load-bearing premises both hold:**
>
> - `calibration.py:203` still reads `FROM multiday_predictions p`. Unchanged.
> - **The precedence trap is still live.** `data/condition_weights.json` still holds real fitted values for all three conditions (`above {.60, .05, .35}`, `below {.05, .75, .20}`, `between {.093, .004, .903}`), so a same-day row still resolves at the **condition** tier and never reaches seasonal. Fitting same-day seasonal alone would still be dead code.
> - Sample counts re-measured and **unchanged**: 204 fittable rows all-horizon, **77 at D+0**, 127 at D+1-and-up, 348 settled. Re-run them anyway before sizing.
> - `_nws_days_out_scale` moved `~:9848` → **`:9869`** (call sites `:10474`, `:10494`).
>
> **What batch 79 changed underneath this batch — read before choosing a file shape.** The five calibration files are **no longer tracked**; `git ls-files data/` is empty. Fresh-clone copies now live in **`seeds/`**, applied by **`paths.materialize_missing_seeds()`** only when `data/` lacks the file, with atomic writes (temp + fsync + `os.link`) so a seed can never overwrite learned state. **Any file this batch adds must follow that mechanism.** The implementation note below about coordinating with batch 79 on force-tracking is therefore **resolved** — ignore it and use `seeds/`.
>
> **One live hazard batch 79 surfaced that lands squarely on this batch's subject.** `seeds/seasonal_weights.json`'s `summer` entry had lost its `"_uncalibrated"` flag, so `_blend_weights` treated summer as *calibrated at uniform weights* and suppressed the days-out schedule. Batch 79 repaired the seed. The lesson for this batch: **an all-uniform weight dict without `_uncalibrated` is indistinguishable from a real fit at the tier check**, and that is exactly the failure mode a new same-day tier can reintroduce. Whatever "declined to fit" shape you choose must set the flag, and a test should pin that an undecorated uniform dict does not satisfy the tier.

**Files owned (once unblocked): `calibration.py`, `weather_markets.py`, `ml_bias.py`, `main.py`, `tracker.py`.**

**This is not a new proposal.** Separate calibration for single-day and multi-day was the original design intent, confirmed by the user 2026-08-26. Temperature scaling already implements it; blend-weight calibration never did. This batch closes that gap.

## The asymmetry

**Temperature scaling honours the separation.** `data/temperature_scale.json` carries a dedicated `sameday` key (`T=3.829, n=102`) beside `global` (`T=4.601, n=68`), and `ml_bias.py` (~`:793-806`) is explicit that same-day trades use it with **"no fallback to global/multi-day T"**, gated on 20 settled same-day trades. It separates hourly from ordinary same-day for the same reason. Note how far apart the fitted values are — 3.83 vs 4.60 — the separation is doing real work, not ceremony.

**Blend-weight calibration does not.** `calibration.py`'s `_load_rows()` (~`:203`) selects `FROM multiday_predictions p`, the view defined as `days_out IS NULL OR days_out >= 1`. Its outputs carry no horizon dimension at all:

| File | Keys |
|---|---|
| `seasonal_weights.json` | `winter`, `spring`, `summer`, `fall` |
| `condition_weights.json` | `above`, `below`, `between` |
| `city_weights.json` | *(empty)* |

`weather_markets.py` (~`:1340-1341`) loads them into module-level `_SEASONAL_WEIGHTS` / `_CONDITION_WEIGHTS`, so same-day trades are priced with weights fitted exclusively on multi-day rows.

**Precise wording matters here, because the code IS `days_out`-aware — just not in the way that helps.** `_nws_days_out_scale(weights, days_out)` (~`:9848`) decays the NWS weight at longer horizons, and its own docstring says: *"Scale factor: 1.0x at days_out=1 (no change — **calibration data is at d=1**), decaying 10% per day beyond that."* Its first guard is:

```python
if w_nws == 0.0 or days_out <= 0:
    return weights          # days_out=0 -> the d=1 weights, unmodified
```

So the system already knows its calibration is d=1-based, handles d≥2 by decay, and passes **d=0 straight through untouched**. Same-day is not overlooked by accident; it falls into the one branch that applies the multi-day fit verbatim.

**D+0 is 56% of the settled population** (196 of 348), so the majority regime is being weighted by a fit derived from the minority.

## The sample, measured 2026-08-26

Rows with all three of `ensemble_prob` / `nws_prob` / `clim_prob` populated and settled — the fit's actual input:

| Population | Rows |
|---|---|
| All horizons | 204 |
| **D+0** | **77** (all `method='ensemble'`) |
| D+1 and up | 127 — what the current fit uses |

**`metar_lockout` carries none of the three probs: 0 of 106 rows.** That is structural, not missing data — the ensemble/Gaussian block sits behind `if not metar_locked:` and `blended_prob` comes from `_metar_blended_prob`. The lockout path was never a blend-weight candidate and must not be counted as one when sizing this.

Against the existing floors:

| Fit | Current floor | D+0 supply | Verdict |
|---|---|---|---|
| seasonal | see caveat below | 77 rows | plausibly fittable |
| condition | 60 per condition | 77 across above/below/between | not yet |
| city | 50 per city | 77 across ~20 cities | not for a long time |

**Re-derive the seasonal floor yourself — do not trust a number from this file.** The cron log's `"only 7 validation rows (need 10)"` belongs to `calibrate_blend_weights`, which is a *different* calibrator from `calibrate_seasonal_weights`; an earlier draft of this batch conflated them. Read each calibrator's own floor in `calibration.py` before sizing anything.

## ⚠ THE TRAP THAT MAKES THE OBVIOUS PLAN A NO-OP

**Fitting same-day seasonal weights alone would change nothing.** `_blend_weights`'s precedence is:

```
city  ->  condition  ->  seasonal  ->  hardcoded
```

Each tier returns early if its calibration is present and not `_uncalibrated`. And `condition_weights.json` currently holds **real fitted values**, not neutral placeholders:

```json
{"above":   {"ensemble": 0.60, "climatology": 0.05,  "nws": 0.35},
 "below":   {"ensemble": 0.05, "climatology": 0.75,  "nws": 0.20},
 "between": {"ensemble": 0.093, "climatology": 0.004, "nws": 0.903}}
```

So a same-day row reaches the **condition** tier and returns there, having never consulted seasonal. Fitting the one tier the sample supports would be dead code while the tier above it still answers from multi-day data.

**This is what makes the batch's decision a chain-level question, not a per-tier one.** Do not implement tier by tier.

## The item

Add a horizon dimension to blend-weight calibration so same-day is fitted from same-day rows.

**The decision that matters, and it is the whole batch — `AskUserQuestion`:** does same-day get its **own precedence chain**, and what sits at the bottom of it?

- **(a) A separate same-day chain that never consults a multi-day tier.** Same-day resolves `city_sameday -> condition_sameday -> seasonal_sameday -> hardcoded`, skipping any tier it cannot fit rather than borrowing the multi-day one. Today that means it would use same-day *seasonal* and fall to *hardcoded* for city/condition. This is what "completely separate" actually implies, and it is the rule temperature scaling already follows verbatim ("no fallback to global/multi-day T"). It is also the only option under which fitting same-day seasonal has any effect at all.
- **(b) Per-tier fallback to the multi-day fit.** Preserves whatever signal the multi-day weights carry — but a same-day row would still resolve at the multi-day *condition* tier, so the same-day seasonal fit stays unreachable and the split is cosmetic.

**(a) is the only option that does anything**, which is a strong argument for it, but it is still the user's call because it means same-day gives up the fitted `above`/`below`/`between` weights and falls to hardcoded until it has 60 rows per condition of its own. Quantify that cost before asking: compare the hardcoded weights against the current condition weights so the question is concrete rather than abstract.

Note `calibration.py` already has machinery for "declined to fit" — it logs a thin-sample refusal and returns uncalibrated so `calibrate_and_save` preserves existing weights. Reuse that shape rather than inventing one; the open question is only what the same-day path *reads* when a tier declines.

**Second, smaller decision:** whether `days_out=0` is the right boundary, or whether the split should be same-day / next-day / multi-day. The existing `multiday_predictions` view draws it at `>= 1`, and temperature scaling's `sameday` key uses the same line, so consistency argues for `days_out=0` — but D+1 is 135 of 348 settled rows and is arguably its own regime.

## Implementation notes

- `calibration.py`'s `_load_rows()` is shared by all three calibrators; parameterise the horizon rather than forking it. Read its `_LOAD_ROWS_COND_CLAUSE` / `_LOAD_ROWS_COND_PARAMS` handling first — there is an existing condition-type exclusion that must survive.
- **`_nws_days_out_scale`'s `days_out <= 0` early return needs revisiting as part of this.** Today it is the line that hands the d=1 fit to same-day unchanged. Once same-day has its own weights, that guard means something different and may be wrong — decide explicitly rather than leaving it.
- The output files gain a horizon level. Decide the shape deliberately: nesting (`{"sameday": {"winter": {...}}}`) versus sibling files (`seasonal_weights_sameday.json`). **Whichever you pick, note that these five calibration files are force-tracked in git despite `data/` being gitignored, and a `git restore .` silently reverts them to uncalibrated seeds** — that is its own open backlog entry, and adding files makes it worse. Coordinate with batch 79, which owns that entry.
- `weather_markets.py`'s module-level `_SEASONAL_WEIGHTS` / `_CONDITION_WEIGHTS` are loaded once at import. A horizon-aware read must not turn into a per-call file read on the pricing path.
- Do **not** fold `metar_lockout` rows into any of this. They carry none of the three inputs, and batch-75 spent a session removing exactly this kind of population mixing from `forecast_temp_f`.

## Process — follow the 29-step implementation workflow in full

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`. Full ceremony, no downgrade: this changes weights on the live pricing path.

(1) Re-verify everything, **including the row counts above** — they are hours old, and D+0 accrues. Re-run them; do not inherit. (3) `AskUserQuestion` for the fallback rule and the horizon boundary before any code. (7) Mutation-tested tests via **Edit**-revert. The essential test: a same-day trade must use the same-day weights and **not** the multi-day ones — pin it by fitting deliberately different values for the two horizons and asserting which one a D+0 prediction picks up. An absence assertion (multi-day weights not used) needs a positive control (a D+1 prediction does use them). (8) Scoped: `tests/test_calibration.py`, `tests/test_ml_bias.py`, `tests/test_weather_markets.py`, `tests/test_tracker.py`. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Measure the before/after.** This changes live pricing inputs, so the resolution should record what the same-day seasonal weights actually came out as against the multi-day ones. If they land close together, that is itself the finding — it would mean the pooling was harmless and the separation is insurance rather than a correction. If they diverge like the T values did (3.83 vs 4.60), it quantifies what the pooled fit was costing.
