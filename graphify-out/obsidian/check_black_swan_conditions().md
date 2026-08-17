---
source_file: "alerts.py"
type: "code"
community: "Community 170"
location: "L447"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_170
---

# check_black_swan_conditions()

## Connections
- [[dot-test_brier_check_failure_fails_closed()]] - `calls` [EXTRACTED]
- [[dot-test_brier_check_still_runs_when_trades_is_empty()]] - `calls` [EXTRACTED]
- [[dot-test_consecutive_loss_below_threshold_ok()]] - `calls` [EXTRACTED]
- [[dot-test_consecutive_loss_triggers()]] - `calls` [EXTRACTED]
- [[dot-test_daily_loss_condition_works_without_balance_param()]] - `calls` [EXTRACTED]
- [[dot-test_days_out_none_does_not_crash()]] - `calls` [EXTRACTED]
- [[dot-test_no_conditions_on_clean_trades()]] - `calls` [EXTRACTED]
- [[dot-test_no_side_consecutive_losses_trigger_black_swan()]] - `calls` [EXTRACTED]
- [[dot-test_no_side_consecutive_wins_not_black_swan()]] - `calls` [EXTRACTED]
- [[dot-test_none_settled_at_does_not_crash_daily_loss_condition()]] - `calls` [EXTRACTED]
- [[CircuitBreaker]] - `semantically_similar_to` [INFERRED]
- [[FlashCrashCB]] - `semantically_similar_to` [INFERRED]
- [[P10.2 Detect extreme abnormal conditions that warrant emergency shutdown.…]] - `rationale_for` [EXTRACTED]
- [[_recent_settled()]] - `calls` [EXTRACTED]
- [[_trade_lost()]] - `calls` [EXTRACTED]
- [[alerts.py]] - `contains` [EXTRACTED]
- [[alerts.py Grade Rubric]] - `references` [EXTRACTED]
- [[brier_score()]] - `calls` [EXTRACTED]
- [[count_settled_predictions()]] - `calls` [EXTRACTED]
- [[get_today_live_loss()]] - `semantically_similar_to` [INFERRED]
- [[run_black_swan_check()]] - `calls` [EXTRACTED]
- [[test_alerts_side.py]] - `imports` [EXTRACTED]
- [[test_p9_p10.py]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_170