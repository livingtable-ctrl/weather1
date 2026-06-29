# MODULE: cron.py

## File Size Warning
cron.py is large and your test list is 4 files. Read the source file in 2,000-line
chunks if it exceeds 2,000 lines. Do not begin grading until you have read all of it.

## Before You Start
Read `tests/test_cron_integration.py`, `tests/test_cron_lock.py`,
`tests/test_cron_trade_updates.py`, and `tests/test_main_cron_smoke.py` before grading.

## TIER 1 Functions
The main cron cycle function, the settlement loop, the kill switch check, the signal
sort + cap enforcement block, the ensemble pin auto-renewal block, the auto-calibration
trigger, and the Brier alert check.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: Kill switch is checked before EACH individual order placement, not once per
  cycle. A kill switch activated mid-scan must stop remaining orders in that cycle.
- AC2: Same-day cap (`MAX_SAME_DAY_POSITIONS` / `MAX_SAME_DAY_SPEND`) and multi-day
  cap (`MAX_POSITIONS_PER_DATE` / `MAX_DAILY_SPEND`) are enforced independently. A
  same-day trade must not consume a multi-day slot and vice versa.
- AC3: Signals are sorted by Kelly fraction descending before any date-cap slot is
  consumed. A weaker signal must not claim the last cap slot over a stronger signal for
  the same date.
- AC4: The 24h settlement gate (`close_time + 24h < now`) is enforced on ALL three
  settlement paths: normal settlement, `needs_manual_settle` path, and black swan
  forced settlement. Trades with NULL `close_time` (pre-2026-05-28) must be skipped,
  not crashed.
- AC5: The black swan Brier check is invoked with `min_days_out=1`. Trace the call
  into `alerts.py` — verify the argument is passed, not defaulted to 0 or missing.
- AC6: The ensemble pin auto-renewal reads `multiday_directional_accuracy` (not raw
  `directional_accuracy`) from `get_edge_realization_rate()`. Confirm the exact dict
  key. This IS correctly filtered — verify it rather than flag it.
- AC7: Auto-calibration trigger: confirm it reads `count_settled_predictions()`
  (multi-day only), calls `calibrate_and_save()`, then updates the sentinel file.
  All three steps must be present.
