# Batch 53: IDR/EasyUQ calibration challenger (DEFERRED — calibration cluster's slot; replay may run any idle day)

## Context

Repo: weather1. Source: Expansion Dossier B3 (score 7.5, rank 5), Rev 4, 2026-08-24. Sequencing: the project's standing order puts the calibration/ML cluster LAST (after remaining backlog, DEMO_BASE smoke test, host move). The <1-day replay experiment below is cheap enough to run any idle day; **productionizing waits for the cluster's slot** unless the user explicitly promotes it. Coordinate with the deferred-calibration backlog items (forecast-condition covariates, cross-city pooling, data-driven sigma L11595, NBM quantile graduation) — IDR is a distinct method class, not a rename of any of them, but they compete for the same settled-sample budget.

Files: `ml_bias.py` (EMOS train/gate path), possibly `calibration.py`; replay script in scratchpad first, production code only after the gate passes.

Ceremony: full 29-step workflow, opus review effort=high if productionized (calibration feeds sizing). The replay alone: LOW-tier.

## The idea

Fit Isotonic Distributional Regression (nonparametric, hyperparameter-free, CRPS-optimal within monotone models) on (blend forecast → settled temperature) pairs and let it COMPETE with EMOS under the existing held-out-CRPS activation gate. EMOS context: still disabled pending the 40-row ens_var floor (backlog L3000); IDR needs only forecast/outcome pairs — 329 settled outcomes existed 2026-08-24 and grow daily.

**Runtime constraint (verified 2026-08-24; REASON CORRECTED 2026-08-25, do not rediscover):** the PyPI package `isodistrreg` requires Python ≥3.13 in every release. The original text said that was "incompatible with this repo's 3.12" — wrong about the local interpreter, which is **3.14.5** and would satisfy it. The binding constraint is **CI**: `.github/workflows` pins `python-version: "3.12"` and `pyproject.toml` sets ruff's `target-version = "py312"`, so a dependency needing ≥3.13 still could not ship without moving CI first. The conclusion is unchanged; only its stated reason was wrong. Use scikit-learn's `IsotonicRegression` (sklearn is already in requirements.txt, imported by ml_bias.py): per-threshold isotonic fits on exceedance indicators reproduce IDR's predictive CDFs with zero new dependencies. PAVA by hand (~100 lines) is the fallback if sklearn's shape doesn't fit.

Evidence honesty (from the dossier, citations corrected in its Rev 3): Henzi/Ziegel/Gneiting JRSS-B 2021 (methodology); Walz et al., SIAM Review 66(1):91-122, Feb 2024 (WeatherBench **T850 gridded** temperature + a precip case — adjacent variables, not airport TMAX); Walz et al. arXiv:2401.03746 (tropical-Africa 24h precip, "CNN+EasyUQ clearly outperforms all competitors"). The evidence becomes direct only via the replay on the bot's own settled history — that's the whole point of the gate below.

## Go/no-go validation (the batch's first and possibly only deliverable, <1 day)

Leave-one-out (or walk-forward, matching the existing harness) replay over predictions.db's settled outcomes: CRPS of IDR(forecast_temp_f → settled_temp_f) vs the current sigma-Gaussian and vs EMOS-where-active, identical splits. Pool cities/seasons (per-city n is too thin); document the pooling. **Gate: IDR mean CRPS ≥5% better than the incumbent on held-out data.** Fail → write the numbers to backlog.txt, close the idea, done — that is a successful batch outcome too.

## If the gate passes

Wire IDR as a challenger inside the existing emos-train/activate/deactivate ceremony (the confirmation-gate machinery built 2026-08-16) — same dry-run default, same typed-confirm activation, same held-out-CRPS comparison printed. Do NOT invent a parallel activation mechanism. Remember the contamination lesson (feedback_reverify_correlation_after_contamination_fix): re-run the replay against the final production-shaped code before trusting the number that justifies activation.

## Constraints

- Monotonicity is IDR's core assumption — if the replay shows bias flipping sign across the forecast range, report it; don't force-fit.
- Scoped tests: `tests/test_ml_bias*.py`, `tests/test_calibration*.py`, new test file. **Never the full suite.**
