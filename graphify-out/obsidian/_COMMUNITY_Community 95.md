---
type: community
cohesion: 0.10
members: 27
---

# Community 95

**Cohesion:** 0.10 - loosely connected
**Members:** 27 nodes

## Members
- [[dot-__init__()_11]] - code - circuit_breaker.py
- [[dot-__init__()_12]] - code - circuit_breaker.py
- [[dot-_load_cooldowns()]] - code - circuit_breaker.py
- [[dot-_load_history()]] - code - circuit_breaker.py
- [[dot-_save_cooldowns()]] - code - circuit_breaker.py
- [[dot-_save_history()]] - code - circuit_breaker.py
- [[dot-check()_1]] - code - circuit_breaker.py
- [[dot-is_in_cooldown()]] - code - circuit_breaker.py
- [[dot-test_rapid_successive_calls_skip_disk_save_but_still_detect_crash()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_save_resumes_once_interval_elapses()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_second_instance_does_not_false_positive_on_small_move()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_second_instance_on_same_path_detects_crash_from_first()]] - code - tests/test_flash_crash_cb.py
- [[2026-07-12 check() now fires on every live WS tick (kalshi_ws.py's…]] - rationale - tests/test_flash_crash_cb.py
- [[FlashCrashCB]] - code - circuit_breaker.py
- [[Load persisted cooldowns from disk, discarding any that have already expired.]] - rationale - circuit_breaker.py
- [[Load persisted price history from disk, discarding any observations already…]] - rationale - circuit_breaker.py
- [[Per-market flash crash detection. Trips when price moves  threshold_pct within…]] - rationale - circuit_breaker.py
- [[Persist current (non-expired) cooldowns to disk atomically.]] - rationale - circuit_breaker.py
- [[Persist current (non-expired) price history to disk atomically.]] - rationale - circuit_breaker.py
- [[Proves the actual point of persisting _history to disk two SEPARATE…]] - rationale - tests/test_flash_crash_cb.py
- [[Record price and return True if this observation triggered a crash. Called from…]] - rationale - circuit_breaker.py
- [[TestFlashCrashCBHistoryPersistence]] - code - tests/test_flash_crash_cb.py
- [[TestFlashCrashCBHistorySaveThrottle]] - code - tests/test_flash_crash_cb.py
- [[Tests for per-market flash crash circuit breaker.]] - rationale - tests/test_flash_crash_cb.py
- [[flash_crash_cb (singleton)]] - code - circuit_breaker.py
- [[test_flash_crash_cb.py]] - code - tests/test_flash_crash_cb.py
- [[test_flash_crash_cb.py_1]] - code - tests/test_flash_crash_cb.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_95
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 365]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 84]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 227]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_Community 167]]
- 1 edge to [[_COMMUNITY_Community 293]]

## Top bridge nodes
- [[FlashCrashCB]] - degree 24, connects to 5 communities
- [[test_flash_crash_cb.py]] - degree 6, connects to 2 communities
- [[dot-_save_cooldowns()]] - degree 4, connects to 1 community
- [[dot-_save_history()]] - degree 4, connects to 1 community
- [[dot-__init__()_11]] - degree 2, connects to 1 community