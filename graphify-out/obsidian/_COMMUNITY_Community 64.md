---
type: community
cohesion: 0.08
members: 34
---

# Community 64

**Cohesion:** 0.08 - loosely connected
**Members:** 34 nodes

## Members
- [[dot-__init__()_9]] - code - circuit_breaker.py
- [[dot-__init__()_10]] - code - circuit_breaker.py
- [[dot-_load_cooldowns()]] - code - circuit_breaker.py
- [[dot-_load_history()]] - code - circuit_breaker.py
- [[dot-_save_cooldowns()]] - code - circuit_breaker.py
- [[dot-_save_history()]] - code - circuit_breaker.py
- [[dot-check()_1]] - code - circuit_breaker.py
- [[dot-is_in_cooldown()]] - code - circuit_breaker.py
- [[dot-setup_method()_36]] - code - tests/test_flash_crash_cb.py
- [[dot-test_cooldown_expires()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_cooldown_prevents_trading()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_crash_on_large_move()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_different_tickers_independent()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_no_cooldown_on_clean_ticker()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_no_crash_on_first_observation()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_no_crash_on_small_move()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_rapid_successive_calls_skip_disk_save_but_still_detect_crash()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_save_resumes_once_interval_elapses()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_second_instance_does_not_false_positive_on_small_move()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_second_instance_on_same_path_detects_crash_from_first()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_upward_spike_also_triggers()]] - code - tests/test_flash_crash_cb.py
- [[2026-07-12 check() now fires on every live WS tick (kalshi_ws.py's…]] - rationale - tests/test_flash_crash_cb.py
- [[FlashCrashCB]] - code - circuit_breaker.py
- [[Load persisted cooldowns from disk, discarding any that have already expired.]] - rationale - circuit_breaker.py
- [[Load persisted price history from disk, discarding any observations already…]] - rationale - circuit_breaker.py
- [[Per-market flash crash detection. Trips when price moves  threshold_pct within…]] - rationale - circuit_breaker.py
- [[Persist current (non-expired) cooldowns to disk atomically.]] - rationale - circuit_breaker.py
- [[Persist current (non-expired) price history to disk atomically.]] - rationale - circuit_breaker.py
- [[Proves the actual point of persisting _history to disk two SEPARATE…]] - rationale - tests/test_flash_crash_cb.py
- [[Record price and return True if this observation triggered a crash. Called from…]] - rationale - circuit_breaker.py
- [[TestFlashCrashCB]] - code - tests/test_flash_crash_cb.py
- [[TestFlashCrashCBHistoryPersistence]] - code - tests/test_flash_crash_cb.py
- [[TestFlashCrashCBHistorySaveThrottle]] - code - tests/test_flash_crash_cb.py
- [[flash_crash_cb (singleton)]] - code - circuit_breaker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_64
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 30]]
- 1 edge to [[_COMMUNITY_Community 76]]
- 1 edge to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 7]]

## Top bridge nodes
- [[FlashCrashCB]] - degree 23, connects to 4 communities
- [[TestFlashCrashCB]] - degree 11, connects to 1 community
- [[TestFlashCrashCBHistoryPersistence]] - degree 5, connects to 1 community
- [[TestFlashCrashCBHistorySaveThrottle]] - degree 5, connects to 1 community
- [[dot-_save_cooldowns()]] - degree 4, connects to 1 community