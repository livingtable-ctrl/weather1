---
type: community
cohesion: 0.10
members: 27
---

# Community 97

**Cohesion:** 0.10 - loosely connected
**Members:** 27 nodes

## Members
- [[A canceled (no-fill) order today must not block re-entry -- same reasoning as…]] - rationale - tests/test_dedup.py
- [[A pendingsentfilled order today must still block re-entry (P1-13).]] - rationale - tests/test_dedup.py
- [[A ticker logged via log_order today must return True for the same side.]] - rationale - tests/test_dedup.py
- [[A ticker never traded today must return False.]] - rationale - tests/test_dedup.py
- [[A ticker with only a failed order today must return False (P1-13).]] - rationale - tests/test_dedup.py
- [[British cancelled spelling (written by older GTC-timer paths) must also be…]] - rationale - tests/test_dedup.py
- [[P1-11 target_date fixture must always return a future date, not a hardcoded…]] - rationale - tests/test_dedup.py
- [[P2-A dedup guard must fire in live=True mode, not just paper mode. When a…]] - rationale - tests/test_dedup.py
- [[Return True if this ticker+side was successfully ordered today (UTC). Excludes…]] - rationale - execution_log.py
- [[Tests for P1.5 — was_traded_today() daily dedup guard in execution_log.]] - rationale - tests/test_dedup.py
- [[Traded KXTEST must not block a different ticker.]] - rationale - tests/test_dedup.py
- [[Traded yes must not block a separate no trade on the same ticker.]] - rationale - tests/test_dedup.py
- [[_auto_place_trades must skip an opp if was_traded_today returns True.]] - rationale - tests/test_dedup.py
- [[test_auto_place_trades_skips_already_traded_today()]] - code - tests/test_dedup.py
- [[test_dedup.py]] - code - tests/test_dedup.py
- [[test_dedup.py_1]] - code - tests/test_dedup.py
- [[test_live_mode_dedup_blocks_already_traded_ticker()]] - code - tests/test_dedup.py
- [[test_target_date_fixture_is_future()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_canceled_order()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_different_side()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_different_ticker()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_legacy_cancelled_spelling()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_new_ticker()]] - code - tests/test_dedup.py
- [[test_was_traded_today_ignores_failed_orders()]] - code - tests/test_dedup.py
- [[test_was_traded_today_true_after_order()]] - code - tests/test_dedup.py
- [[test_was_traded_today_true_for_non_failed_status()]] - code - tests/test_dedup.py
- [[was_traded_today()]] - code - execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_97
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 3 edges to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 180]]

## Top bridge nodes
- [[was_traded_today()]] - degree 17, connects to 3 communities
- [[test_dedup.py_1]] - degree 3, connects to 2 communities
- [[test_dedup.py]] - degree 14, connects to 1 community