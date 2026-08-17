---
type: community
cohesion: 0.20
members: 10
---

# Community 395

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[49 load_correlations_from_backtest  save_correlations round-trip.]] - rationale - tests/test_trading.py
- [[dot-test_fallback_to_hardcoded_when_file_missing()]] - code - tests/test_trading.py
- [[dot-test_save_and_reload()]] - code - tests/test_trading.py
- [[dot-test_save_correlations_valid_json()]] - code - tests/test_trading.py
- [[dot-test_unknown_pair_returns_zero_after_load()]] - code - tests/test_trading.py
- [[After loading, unknown city pairs return 0.0.]] - rationale - tests/test_trading.py
- [[TestCorrelationPersistence]] - code - tests/test_trading.py
- [[When correlations.json is absent, returns _HARDCODED_CORR.]] - rationale - tests/test_trading.py
- [[save_correlations produces valid JSON with pipe-separated keys.]] - rationale - tests/test_trading.py
- [[save_correlations writes JSON; load_correlations_from_backtest reads it back.]] - rationale - tests/test_trading.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_395
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 86]]

## Top bridge nodes
- [[TestCorrelationPersistence]] - degree 6, connects to 1 community