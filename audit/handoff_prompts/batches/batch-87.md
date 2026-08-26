# Batch 87: recalibrate on the unbiased population (direction-entry option 2)

## Context

Repo: weather1. Written 2026-08-26 against master `0d69c25d` — **re-verify current before starting**. Live trading dormant.

**Files owned: `ml_bias.py`, `calibration.py`, `tracker.py`, `data/temperature_scale.json` (via `seeds/`).**
**Read-only: `weather_markets.py` — batch 88 owns it.**

This is option 2 of `backlog.txt`'s entry *"PROJECT DIRECTION AFTER THE NO-EDGE RESULT"*. Read that entry and its two parents (*"THE MODEL'S 'EDGE' IS ITS OWN MISCALIBRATION"* and the follow-up on closed exits) before starting. They contain every number below.

## The item

**Every calibration fit in this repo is trained on `predictions`, which is the one population where the defect being calibrated away is invisible.** `predictions` only ever holds rows that cleared the edge gates: its minimum |forecast − market| is 0.0984 and it contains **zero** rows below the 0.08 floor. `analysis_attempts` now holds 584 scored rows, **535 of which were never traded**, with a minimum separation of 0.0011.

Measured on the unbiased population, core temperature families (538 of 584):

```
calibration regression  y = a + b*p
  MODEL    slope 1.233 (se 0.078)  intercept -0.238
  MARKET   slope 1.107 (se 0.044)  intercept -0.067
```

`b > 1` means probabilities compressed toward 0.5. Temporal split, Platt fitted on the earlier 322 rows and applied to the later 216:

```
HELD-OUT Brier   raw 0.1756   CALIBRATED 0.1473   market 0.1106
fitted a=-0.6833  b=1.4168
```

**Recalibration removes ~44% of the excess Brier.** It does **not** create edge — calibrated vs market is still +0.0366 at t=+3.50 — and the batch must not be described or resolved as if it does. This is correctness work: it makes every downstream statistic honest.

## What to decide — `AskUserQuestion`

1. **Which population fits the calibration.** The obvious answer is `analysis_attempts`, but it is not free: those rows carry `forecast_prob`/`market_prob` and an outcome, while `predictions` carries the richer feature set the current fits use. Determine what the existing fit actually consumes before assuming a swap is possible.
2. **Whether to refit `temperature_scale.json` too, or only the probability calibration.** They are different objects — one maps °F error, the other maps probabilities. Do not conflate them.
3. **Fit form.** Platt (2-parameter, what I tested) versus the existing temperature-scaling shape versus isotonic. Platt is the measured baseline; anything else must beat it held-out.

## Constraints specific to this batch

- **Fit and evaluate on a temporal split, always.** Never report an in-sample improvement. The numbers above come from fitting on the earlier 60% and scoring the later 40%; reproduce that discipline or the result is meaningless.
- **Do not re-score the same rows with a fit trained on them** when reporting the post-change effect.
- **`_uncalibrated` is load-bearing.** Batch 79 found `seeds/seasonal_weights.json`'s summer entry had lost the flag, so `_blend_weights` read uniform weights as a real fit. Any "declined to fit" state must set it, and a test must pin that an undecorated uniform dict does not satisfy the tier.
- **`seeds/` is the mechanism** — `paths.materialize_missing_seeds()`. Never `git add -f` into `data/`.
- Batch 82 (`09b3b394`) just landed same-day blend-weight fitting and found *"the pooling was helping, not costing"*. Read its resolution note; it touched `calibration.py` and its conclusion constrains yours.

## Process — 29-step workflow in full

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`. No downgrade: this changes live pricing inputs.

(1) Re-verify every number above — they are hours old and `analysis_attempts` accrues ~23/day. (3) `AskUserQuestion` for the three decisions. (7) Mutation-test via **Edit**, never a script. (8) Scoped: `tests/test_ml_bias.py`, `tests/test_calibration.py`, `tests/test_tracker.py`, `tests/test_calibration_decomposition.py`, `tests/test_model_vs_market_brier.py` — and confirm with `grep -rln "<symbol>" tests/*.py` per symbol you touch rather than trusting this list. **Never the bare full suite.** (9) Lint with `python -m pre_commit run --files <paths>` — **there is no installed git hook**, so `git commit` lints nothing. If you add or edit anything under `audit/`, also run CI's own `ruff check .` and `mypy . --ignore-missing-imports --implicit-optional --no-error-summary`, because `.pre-commit-config.yaml` excludes `^audit/` and CI does not. (11) Independent opus review at `effort: high`. (13) Address every finding. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase. (19) `python backlog_index.py`.

**Report the before/after held-out honestly**, including if it comes out worse than my numbers. A calibration that helps in-sample and not out-of-sample is the failure mode this entire line of work exists to expose.
