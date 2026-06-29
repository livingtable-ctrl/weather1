# MODULE: calibration.py

## Before You Start
Read `tests/test_calibration.py` before grading.

## TIER 1 Functions
`_load_rows()`, `calibrate_seasonal_weights()`, `calibrate_city_weights()`,
`calibrate_condition_weights()`, `calibrate_and_save()`.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `_load_rows()` and every inline calibration query includes
  `AND (p.days_out IS NULL OR p.days_out >= 1)` — same-day METAR trades must not
  corrupt blend weight calibration.
- AC2: Auto-calibration does not overwrite T values in `temperature_scale.json` when
  EMOS is deployed. EMOS owns T post-deploy. The three-layer defense preventing
  premature above/below auto-calibration lives in `calibrate_condition_weights()`:
  look for `CONDITION_MIN` (must be 60), `MIN_VAL_ROWS` (must be 10), and
  `BRIER_IMPROVEMENT_GATE` (must be 0.005). Verify all three are present and correct.
- AC3: Calibration data is evaluated on held-out data, not the same rows used for
  optimization. Look for any query that uses the same date range for both grid search
  and evaluation — this is look-ahead bias if present.
