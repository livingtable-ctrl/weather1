# MODULE: nws.py

## Before You Start
Read `tests/test_obs_weight.py` and `tests/test_gaussian_prob.py` before grading.

## TIER 1 Functions
The main NWS probability function, `obs_prob()` (intraday METAR),
`_nws_days_out_scale()` or equivalent weight scaling function, and any function that
computes the sigma value.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: The sigma ladder is EXACTLY this — any deviation is a CRITICAL bug:
  - `days_out = 0` → `sigma = 1.0`
  - `days_out = 1` AND `condition_type = "between"` → `sigma = 1.0`
  - `days_out = 1` AND condition_type is above or below → `sigma = 2.0`
  - `days_out ≤ 2` → `sigma = 2.0`
  - `days_out ≤ 5` → `sigma = 3.0`
  - else → `sigma = 4.0`
  The between-only asymmetry at `days_out=1` is intentional engineering that fixes a
  structural 38.4% cap issue for between-condition markets. Do NOT flag as inconsistent.
  Flag any deviation from the values above.
- AC2: `obs_prob()` (intraday METAR observation function — NOT the NWS forecast
  function) uses `sigma = 3.5`. If it uses `sigma = 1.0`, it would produce near-binary
  probabilities from an intraday reading before the daily high is reached.
- AC3: `_nws_days_out_scale()` or equivalent returns 0 (or the NWS weight is otherwise
  zeroed) when `days_out == 0`. Same-day above/below trades use METAR lock-in; NWS
  also weighted at `days_out=0` would double-count the NWS signal.
