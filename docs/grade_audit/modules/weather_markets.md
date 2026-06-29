# MODULE: weather_markets.py

## CRITICAL — File Size Warning
This file is 6,481 lines. You MUST read it in 2,000-line chunks before grading.
Read(offset=0, limit=2000) → Read(offset=2000, limit=2000) → keep going until EOF.
Do not begin grading any section until you have finished reading every line.

## Before You Start
Read `tests/test_forecasting.py`, `tests/test_gaussian_prob.py`,
`tests/test_edge_threshold.py`, `tests/test_signal_quality.py`, and
`tests/conftest.py` (autouse fixtures affect all tests) before grading.

## Important: Grade by Section
This file has ~97 functions and 6,481 lines. Grade section by section as defined below.
Every function within a section gets graded. For functions not assigned to a named
section, grade them in Section 9 (all remaining functions, TIER 2).

---

## Section 1 — Ensemble Fetch and Degenerate Guard
Functions: ensemble temperature fetch from GFS/ECMWF/ICON, degenerate ensemble
detection. TIER 1. AC4 applies. I7 applies.

## Section 2 — METAR Lock-in (Same-day Path)
Functions: `_metar_lock_in()` or equivalent inline block for `days_out=0` trades.
TIER 1. AC3 applies. I4 (NULL close_time handling) applies.

## Section 3 — NWS Weight Scaling
Functions: `_nws_days_out_scale()` or equivalent weight scaling function.
TIER 1. AC5 applies. Also verify nws.py AC3 (NWS weight=0 at days_out=0) here.

## Section 4 — Blend Weights Application
Functions: everything that applies seasonal/city/condition weights to produce
`blended_prob`. TIER 1. I1 (days_out filter where applicable), I9 (days_out
threading through blend) apply.

## Section 5 — T-scaling, GBM Bias, Platt Calibration Block
Functions: calls to `apply_temperature_scaling()`, `apply_ml_prob_correction()`,
`apply_platt_per_city()`. TIER 1. AC1 (GBM guard `days_out > 0`), AC2 (Platt guard
`days_out > 0`) apply here. I5 and I6 apply.

## Section 6 — Market Anchor and Model-Market Gap Gate
Functions: market anchor application, `_model_mkt_gap` gate check.
TIER 1.
- If market anchor is applied to same-day trades: mark UNCERTAIN and argue both sides
  (market price near 0/1 at same-day — anchoring toward it may be correct).
- `_model_mkt_gap > 0.25` gate: confirm it applies to both same-day and multi-day, and
  note whether same-day application is appropriate (market has seen the same METAR data).

## Section 7 — Kelly Sizing and Drawdown Scaling
Functions: Kelly fraction computation, drawdown scaling multiplier application,
quantity calculation. TIER 1. I5 (finite guard before Kelly), I8 (drawdown scaling
uses `drawdown_scaling_factor()` not raw balance) apply.

## Section 8 — analyze_trade() Orchestration
The top-level function that calls all of the above. TIER 1.
Key check: does `days_out` thread through correctly from the top of the function to
every sub-call (blend, T-scaling, GBM, Platt, Kelly)? Check I9 explicitly here.

## Section 9 — All Remaining Functions
Everything not covered in Sections 1–8. TIER 2. One line each.

---

## Acceptance Criteria
A function in Sections 1–8 CANNOT score above 7 if it fails any of these.

- AC1: GBM block has `if days_out > 0:` (or equivalent) guard before calling
  `apply_ml_prob_correction()`.
- AC2: Platt block has `if days_out > 0:` (or equivalent) guard before calling
  `apply_platt_per_city()`.
- AC3: METAR lock-in block has `condition_type != "between"` (or equivalent) guard.
  Between-condition markets must not receive METAR lock-in — a current temperature
  reading does not predict the daily high within a 2°F band.
- AC4: Degenerate ensemble (all members identical) returns `None` or skips the trade
  before any blending. A junk probability from an all-identical ensemble must never
  reach Kelly. Note: any ensemble where all 20 members are the same value must trigger
  this guard — returning `[65.0]*20` is degenerate.
- AC5: `_nws_days_out_scale()` or equivalent returns 0 or exits early when
  `days_out == 0`. Prevents NWS double-weighting on top of METAR lock-in for same-day
  above/below trades.
