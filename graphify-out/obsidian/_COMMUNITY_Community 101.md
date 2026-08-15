---
type: community
cohesion: 0.10
members: 27
---

# Community 101

**Cohesion:** 0.10 - loosely connected
**Members:** 27 nodes

## Members
- [[dot-test_already_retired_not_duplicated()]] - code - tests/test_p9_p10.py
- [[dot-test_auto_retire_does_not_retire_good_method()]] - code - tests/test_p9_p10.py
- [[dot-test_auto_retire_skips_insufficient_samples()]] - code - tests/test_p9_p10.py
- [[dot-test_auto_retire_strategies_retires_bad_method()]] - code - tests/test_p9_p10.py
- [[dot-test_brier_score_by_method_rolling_returns_last_n()]] - code - tests/test_p9_p10.py
- [[dot-test_dir_accuracy_guard_allows_retirement_when_direction_bad()]] - code - tests/test_p9_p10.py
- [[dot-test_dir_accuracy_guard_blocks_retirement()]] - code - tests/test_p9_p10.py
- [[dot-test_dir_accuracy_guard_inactive_when_accuracy_none()]] - code - tests/test_p9_p10.py
- [[dot-test_get_retired_strategies_empty()]] - code - tests/test_p9_p10.py
- [[dot-test_rolling_guard_allows_retirement_when_recent_still_bad()]] - code - tests/test_p9_p10.py
- [[dot-test_rolling_guard_blocks_retirement_when_recent_recovered()]] - code - tests/test_p9_p10.py
- [[dot-test_unretire_nonexistent_returns_false()]] - code - tests/test_p9_p10.py
- [[dot-test_unretire_strategy()]] - code - tests/test_p9_p10.py
- [[A method with Brier  0.25 over 20+ predictions should be auto-retired.]] - rationale - tests/test_p9_p10.py
- [[A well-performing method (Brier  0.25) must NOT be retired.]] - rationale - tests/test_p9_p10.py
- [[Both lifetime and rolling Brier are bad — method IS retired (guard doesn't…]] - rationale - tests/test_p9_p10.py
- [[Guard is skipped when directional accuracy is not available — retire normally.]] - rationale - tests/test_p9_p10.py
- [[Helper log a prediction + outcome in the temp tracker DB.]] - rationale - tests/test_p9_p10.py
- [[Lifetime Brier  threshold from old bad trades, but the last 20 settled…]] - rationale - tests/test_p9_p10.py
- [[Method IS retired when directional accuracy is below the guard.]] - rationale - tests/test_p9_p10.py
- [[Method with Brier  0.25 is NOT retired when directional accuracy = guard.…]] - rationale - tests/test_p9_p10.py
- [[Methods with fewer than min_samples predictions are not evaluated.]] - rationale - tests/test_p9_p10.py
- [[Re-running auto_retire on an already-retired method doesn't duplicate it.]] - rationale - tests/test_p9_p10.py
- [[TestStrategyRetirement]] - code - tests/test_p9_p10.py
- [[_log_and_settle()]] - code - tests/test_p9_p10.py
- [[brier_score_by_method_rolling only reflects the most recent `window` rows.]] - rationale - tests/test_p9_p10.py
- [[unretire_strategy removes a retired entry.]] - rationale - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_101
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 50]]
- 2 edges to [[_COMMUNITY_Community 430]]

## Top bridge nodes
- [[_log_and_settle()]] - degree 15, connects to 2 communities
- [[TestStrategyRetirement]] - degree 14, connects to 1 community