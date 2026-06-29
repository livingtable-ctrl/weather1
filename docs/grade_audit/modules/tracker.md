# MODULE: tracker.py

## Before You Start
Read `tests/test_tracker.py` and `tests/test_schema_drift.py` before grading.

## TIER 1 Functions
Every SQL-querying function that computes a Brier score, win rate, calibration metric,
or graduation gate value. Every schema migration function. `init_db()`.
`sync_outcomes()`. `count_settled_predictions()`.

## TIER 2 Functions
Pure display/formatting helpers. `get_history()` (intentionally unfiltered — see
known-intentionals in preamble).

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: Every Brier/win-rate/calibration metric query targets `multiday_predictions`
  view or has explicit `AND (p.days_out IS NULL OR p.days_out >= 1)` — EXCEPT the
  known-intentional unfiltered functions listed in the preamble. Confirm which category
  each query falls into before flagging.
- AC2: `count_settled_predictions()` queries `multiday_predictions`, not raw
  `predictions`. This guards the graduation threshold and auto-calibration trigger.
- AC3: Schema migrations are applied under a PRAGMA user_version check, are safe to
  re-run on an already-migrated DB, and the user_version is updated only AFTER all DDL
  succeeds.
- AC4: `_conn()` enables WAL mode; no connection object is held open across a `yield`
  or async boundary.
- AC5: Any function that touches `close_time` handles NULL gracefully (skip rather than
  crash) — trades before 2026-05-28 have NULL close_time.
