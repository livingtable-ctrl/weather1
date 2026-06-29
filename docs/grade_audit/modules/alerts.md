# MODULE: alerts.py

## Before You Start
Read `tests/test_alerts_side.py`, `tests/test_sprt.py`, and `tests/test_dead_man.py`
before grading.

## TIER 1 Functions
`check_black_swan_conditions()`, `activate_black_swan_halt()`, `run_black_swan_check()`,
`check_anomalies()`, `run_anomaly_check()`, `_is_halt_level()`.

## TIER 2 Functions
`add_alert()`, `remove_alert()`, `get_alerts()`, `mark_triggered()`, `save_alerts()`,
`get_black_swan_status()`, `clear_black_swan_state()`, `_trade_won()`.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `check_black_swan_conditions()` calls the Brier function with `min_days_out=1`
  (or equivalent). Same-day METAR losses must NOT trigger the black swan halt — it is
  designed to detect multi-day model collapse. If the Brier function is called without
  this filter, flag CRITICAL.
- AC2: `activate_black_swan_halt()` executes the halt independently of whether
  notification (email/Slack/etc.) succeeds. Halt logic must not be coupled to
  notification success — a failed notification channel must not prevent the halt.
- AC3: `run_anomaly_check()` and `check_anomalies()` — any win rate or Brier metric
  computed here uses multi-day trades only. Same-day METAR wins would inflate metrics
  and suppress legitimate anomaly alerts.
- AC4: Any SPRT (sequential probability ratio test) logic — verify the null hypothesis
  P0 and alternative hypothesis P1 are correctly ordered (P0=baseline, P1=degraded)
  and that the decision boundaries are not inverted.
