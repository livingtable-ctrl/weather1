# MODULE: ml_bias.py

## Before You Start
Read `tests/test_ml_bias.py` and `tests/test_hmac_bias.py` before grading.

Read `tests/conftest.py`: the `neutral_temperature_scaling` autouse fixture patches
`ml_bias._TEMP_CACHE` to T=1.0 per test. Without knowing this, tests will appear to
not isolate temperature scaling when they do.

## TIER 1 Functions
`train_all_temperature_scaling()`, `apply_temperature_scaling()`,
`train_bias_model()`, `apply_ml_prob_correction()`, `apply_platt_per_city()`,
and any Platt training function.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: Multi-day training query uses `FROM multiday_predictions` or
  `AND (p.days_out IS NULL OR p.days_out >= 1)`. Same-day training query uses
  `AND p.days_out = 0`. These must be separate queries, not one combined query.
- AC2: `apply_temperature_scaling()` is called with a `days_out` keyword argument so
  the correct T path (same-day vs multi-day) is selected. If `days_out` is not passed,
  same-day trades silently get multi-day T scaling.
- AC3: After `train_all_temperature_scaling()` writes `temperature_scale.json`, the
  in-process cache (`_TEMP_CACHE` or equivalent module-level variable) is invalidated —
  set to `None` or equivalent — so trades placed in the same cron cycle use the new
  values. A single `global _TEMP_CACHE; _TEMP_CACHE = None` after the write is the fix
  if missing.
- AC4: `apply_ml_prob_correction()` and `apply_platt_per_city()` are only called for
  `days_out > 0`. If called on same-day trades, multi-day-trained models would
  misapply.

## Special Notes
T=1.0 everywhere in `temperature_scale.json` is intentional (EMOS deployment). The
priors `_T_BELOW_PRIOR=3.0` and `_T_ABOVE_PRIOR=6.0` only apply when T is `None`,
not when T=1.0. Do not flag either as misconfigured.
