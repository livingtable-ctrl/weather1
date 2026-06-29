# MODULE: monte_carlo.py

## Before You Start
Read `tests/test_risk_control.py` and any test referencing `portfolio_var` or
`simulate_portfolio` before grading.

## TIER 1 Functions
All functions: `_cholesky()`, `_repair_psd()`, `load_correlations_from_backtest()`,
`save_correlations()`, `_load_dynamic_correlations()`, `get_city_correlation()`,
`simulate_portfolio()`, `portfolio_var()`.

## TIER 2 Functions
`run_stress_test()`.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `_cholesky()` returns `None` when the matrix is not positive semi-definite
  rather than crashing. `_repair_psd()` must be called before attempting Cholesky on
  any loaded correlation matrix — a corrupted `learned_correlations.json` must not
  crash the VaR computation.
- AC2: `portfolio_var()` handles an empty position list without division by zero or
  NaN. If all open positions are same-day (multi-day portfolio is empty), the function
  must return a valid (near-zero) VaR rather than crashing.
- AC3: Same-day open positions (`days_out=0`) are modelled with a much shorter horizon
  than multi-day positions, OR are excluded from VaR entirely. Same-day markets settle
  the same calendar day — modelling them with the same Monte Carlo horizon as 3-day
  positions overstates VaR and could trigger incorrect risk halts.
- AC4: `save_correlations()` uses the atomic write path — a crash during save must not
  corrupt `learned_correlations.json`.
