# Batch 82: fit same-day blend weights separately — completing the original design

## Context

Repo: weather1. Written 2026-08-26 against master `c9cd4426` — **re-verify current before starting**.

> ## ⛔ BLOCKED on batches 76, 78, 79. Check `git log origin/master` before starting.
>
> Touches `calibration.py`, `ml_bias.py`, `main.py` (owned by batch 79), `weather_markets.py` (76) and `tracker.py` (78). Rebase onto whatever they land.

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

And `weather_markets.py` (~`:1340-1341`) loads them into module-level `_SEASONAL_WEIGHTS` / `_CONDITION_WEIGHTS` applied **regardless of `days_out`**. So same-day trades are priced with weights fitted exclusively on multi-day rows.

**D+0 is 56% of the settled population** (196 of 348), so the majority regime is being weighted by a fit derived from the minority.

## The sample, measured 2026-08-26

Rows with all three of `ensemble_prob` / `nws_prob` / `clim_prob` populated and settled — the fit's actual input:

| Population | Rows |
|---|---|
| All horizons | 204 |
| **D+0** | **77** (all `method='ensemble'`) |
| D+1 and up | 127 — what the current fit uses |

**`metar_lockout` carries none of the three probs: 0 of 106 rows.** That is structural, not missing data — the ensemble/Gaussian block sits behind `if not metar_locked:` and `blended_prob` comes from `_metar_blended_prob`. The lockout path was never a blend-weight candidate and must not be counted as one when sizing this.

Against the existing floors, that gives a clear split of what is available now:

| Fit | Current floor | D+0 supply | Verdict |
|---|---|---|---|
| seasonal | 10 validation rows | 77 → ~15 validation at the existing holdout | **fittable today** |
| condition | 60 per condition | 77 across above/below/between | not yet |
| city | 50 per city | 77 across ~20 cities | not for a long time |

## The item

Add a horizon dimension to blend-weight calibration so same-day is fitted from same-day rows.

**The decision that matters, and it is the whole batch — `AskUserQuestion`:** what should same-day use when its own fit is too thin, which is the case for city and condition today?

- **(a) Neutral defaults.** This is what "completely separate" actually implies, and it is the rule temperature scaling already follows ("no fallback to global/multi-day T"). Consistent with existing precedent; costs predictive power while the sample is thin.
- **(b) Fall back to the multi-day fit.** Preserves whatever signal the multi-day weights carry, but it re-creates exactly the pooling this batch exists to remove, just with extra steps.

**(a) is the consistent answer** — it is the same rule already applied one layer up, and a fallback that silently reinstates multi-day weights would make the split cosmetic. But it is the user's call, because it means same-day condition/city weights sit at neutral for months.

Note `calibration.py` already logs its own thin-sample behaviour (`"only 7 validation rows (need 10) — returning uncalibrated so calibrate_and_save preserves existing weights"`), so the machinery for "declined to fit" exists; the question is only what the same-day path reads when that happens.

**Second, smaller decision:** whether `days_out=0` is the right boundary, or whether the split should be same-day / next-day / multi-day. The existing `multiday_predictions` view draws it at `>= 1`, and temperature scaling's `sameday` key uses the same line, so consistency argues for `days_out=0` — but D+1 is 135 of 348 settled rows and is arguably its own regime.

## Implementation notes

- `calibration.py`'s `_load_rows()` is shared by all three calibrators; parameterise the horizon rather than forking it. Read its `_LOAD_ROWS_COND_CLAUSE` / `_LOAD_ROWS_COND_PARAMS` handling first — there is an existing condition-type exclusion that must survive.
- The output files gain a horizon level. Decide the shape deliberately: nesting (`{"sameday": {"winter": {...}}}`) versus sibling files (`seasonal_weights_sameday.json`). **Whichever you pick, note that these five calibration files are force-tracked in git despite `data/` being gitignored, and a `git restore .` silently reverts them to uncalibrated seeds** — that is its own open backlog entry, and adding files makes it worse. Coordinate with batch 79, which owns that entry.
- `weather_markets.py`'s module-level `_SEASONAL_WEIGHTS` / `_CONDITION_WEIGHTS` are loaded once at import. A horizon-aware read must not turn into a per-call file read on the pricing path.
- Do **not** fold `metar_lockout` rows into any of this. They carry none of the three inputs, and batch-75 spent a session removing exactly this kind of population mixing from `forecast_temp_f`.

## Process — follow the 29-step implementation workflow in full

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`. Full ceremony, no downgrade: this changes weights on the live pricing path.

(1) Re-verify everything, **including the row counts above** — they are hours old, and D+0 accrues. Re-run them; do not inherit. (3) `AskUserQuestion` for the fallback rule and the horizon boundary before any code. (7) Mutation-tested tests via **Edit**-revert. The essential test: a same-day trade must use the same-day weights and **not** the multi-day ones — pin it by fitting deliberately different values for the two horizons and asserting which one a D+0 prediction picks up. An absence assertion (multi-day weights not used) needs a positive control (a D+1 prediction does use them). (8) Scoped: `tests/test_calibration.py`, `tests/test_ml_bias.py`, `tests/test_weather_markets.py`, `tests/test_tracker.py`. **Never the bare full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Measure the before/after.** This changes live pricing inputs, so the resolution should record what the same-day seasonal weights actually came out as against the multi-day ones. If they land close together, that is itself the finding — it would mean the pooling was harmless and the separation is insurance rather than a correction. If they diverge like the T values did (3.83 vs 4.60), it quantifies what the pooled fit was costing.
