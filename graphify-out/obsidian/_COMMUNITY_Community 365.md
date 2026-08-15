---
type: community
cohesion: 0.20
members: 10
---

# Community 365

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-setup_method()_24]] - code - tests/test_flash_crash_cb.py
- [[dot-test_cooldown_expires()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_cooldown_prevents_trading()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_crash_on_large_move()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_different_tickers_independent()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_no_cooldown_on_clean_ticker()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_no_crash_on_first_observation()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_no_crash_on_small_move()]] - code - tests/test_flash_crash_cb.py
- [[dot-test_upward_spike_also_triggers()]] - code - tests/test_flash_crash_cb.py
- [[TestFlashCrashCB]] - code - tests/test_flash_crash_cb.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_365
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 95]]

## Top bridge nodes
- [[TestFlashCrashCB]] - degree 11, connects to 1 community
- [[dot-setup_method()_24]] - degree 2, connects to 1 community
- [[dot-test_cooldown_expires()]] - degree 2, connects to 1 community