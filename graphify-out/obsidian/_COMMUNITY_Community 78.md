---
type: community
cohesion: 0.07
members: 29
---

# Community 78

**Cohesion:** 0.07 - loosely connected
**Members:** 29 nodes

## Members
- [[dot-test_bad_drawdown_env_var_uses_default()]] - code - tests/test_debug_fixes.py
- [[dot-test_bad_max_daily_loss_env_var_uses_default()]] - code - tests/test_debug_fixes.py
- [[dot-test_bad_position_age_int_var_uses_default()]] - code - tests/test_debug_fixes.py
- [[dot-test_batch_can_set_was_traded_true()]] - code - tests/test_debug_fixes.py
- [[dot-test_batch_does_not_overwrite_was_traded_true()]] - code - tests/test_debug_fixes.py
- [[dot-test_covariance_kelly_uses_zero_entry_prob_not_half()]] - code - tests/test_debug_fixes.py
- [[dot-test_fresh_rows_are_still_inserted()]] - code - tests/test_debug_fixes.py
- [[dot-test_log_prediction_failure_emits_warning()]] - code - tests/test_debug_fixes.py
- [[dot-test_pnl_decomposition_uses_zero_entry_prob()]] - code - tests/test_debug_fixes.py
- [[dot-test_sync_outcomes_logs_on_client_error()]] - code - tests/test_debug_fixes.py
- [[dot-test_valid_env_var_is_used()]] - code - tests/test_debug_fixes.py
- [[Malformed DRAWDOWN_HALT_PCT falls back to 0.50 without crashing.]] - rationale - tests/test_debug_fixes.py
- [[New rows must still be inserted when there's no conflict.]] - rationale - tests/test_debug_fixes.py
- [[Re-running batch_log_analysis_attempts must not reset was_traded to 0.]] - rationale - tests/test_debug_fixes.py
- [[Regression tests for the full-program debug session fixes. Covers A —…]] - rationale - tests/test_debug_fixes.py
- [[TestAnalysisAttemptsUpsert]] - code - tests/test_debug_fixes.py
- [[TestEntryProbFalsyZero]] - code - tests/test_debug_fixes.py
- [[TestEnvVarFallback]] - code - tests/test_debug_fixes.py
- [[TestLogPredictionWarning]] - code - tests/test_debug_fixes.py
- [[TestSyncOutcomesWarning]] - code - tests/test_debug_fixes.py
- [[When log_prediction raises, cmd_analyze logs a warning.]] - rationale - tests/test_debug_fixes.py
- [[entry_prob=0.0 on an open trade must not be replaced by 0.5 in covariance math.]] - rationale - tests/test_debug_fixes.py
- [[fixture_17]] - code
- [[get_attribution must not substitute 0.5 when entry_prob is 0.0.]] - rationale - tests/test_debug_fixes.py
- [[sync_outcomes logs a warning when client.get_market raises.]] - rationale - tests/test_debug_fixes.py
- [[test_debug_fixes.py]] - code - tests/test_debug_fixes.py
- [[tmp_paper()]] - code - tests/test_debug_fixes.py
- [[tmp_tracker()_2]] - code - tests/test_debug_fixes.py
- [[was_traded can go from 0 → 1 via log_analysis_attempt after batch insert.]] - rationale - tests/test_debug_fixes.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_78
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 361]]
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[test_debug_fixes.py]] - degree 13, connects to 4 communities