# MODULE: paper.py

## Before You Start
Read `tests/test_paper.py`, `tests/test_drawdown_tiers.py`,
`tests/test_paper_metrics.py`, and `tests/conftest.py` before grading.

Note: `conftest.py` contains `neutral_temperature_scaling` and
`isolate_condition_weights` autouse fixtures. Without reading conftest, tests will
appear poorly isolated when they are not.

## TIER 1 Functions
`_load()`, `_save()`, `_drawdown_snapshot()`, `is_paused_drawdown()`,
`drawdown_scaling_factor()`, `get_balance()`, `get_peak_balance()`,
`graduation_check()`, `settle_paper_trade()`, `add_paper_trade()`,
`reset_peak_balance()`, `get_edge_realization_rate()`.

## TIER 2 Functions
Display formatters. `get_history()` (intentionally unfiltered).
`get_all_trades()` (intentionally returns everything — see preamble known-intentionals).
`get_max_drawdown_pct()` (intentionally uses raw `get_balance()` as a reporting metric
— do NOT flag under I8).

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: Every function that calls `_save()` holds `_DATA_LOCK` for the entire
  read-modify-write cycle — no gap between `_load()` and `_save()`.
- AC2: `_drawdown_snapshot()` adds back the cost of open same-day positions to compute
  effective balance — and runs entirely inside a single `_DATA_LOCK` acquisition.
- AC3: Every function that gates or scales a trade uses `_drawdown_snapshot()`, not raw
  `get_balance()`. Exception: `get_max_drawdown_pct()` intentionally uses `get_balance()`
  as a reporting metric — do not flag.
- AC4: `graduation_check()` uses the `≤0.23` Brier threshold on the last-50 multi-day
  settled trades. If you see `< 0.20` in the gate logic (not display code), flag
  CRITICAL — the 0.20 threshold is below the theoretical calibration floor of 0.219.
- AC5: `reset_peak_balance()` raises `ValueError` unless `confirmed=True` is passed and
  cannot be bypassed by piping input.
- AC6: `get_edge_realization_rate()` returns a dict containing `multiday_directional_accuracy`
  as a separately-computed key (filtered for multi-day trades only). Confirm the key
  name and that same-day trades are excluded from the multi-day metric.
