---
type: community
cohesion: 0.17
members: 12
---

# Community 313

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-test_consistency_violations_logged_at_warning()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_excess_violations_set_skip_flag()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_find_violations_called_in_source()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_find_violations_detects_inversion()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_find_violations_with_clean_markets_returns_empty()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_skip_flag_blocks_auto_trading()]] - code - tests/test_phase3_batch_e.py
- [[A set of coherent above-threshold markets must produce zero violations.]] - rationale - tests/test_phase3_batch_e.py
- [[More than 5 violations must set consistency_skip=True.]] - rationale - tests/test_phase3_batch_e.py
- [[P(75°)  P(65°) is an impossible inversion — must be flagged.]] - rationale - tests/test_phase3_batch_e.py
- [[P3-14 the consistency check must run after market scan and loghalt on excess…]] - rationale - tests/test_phase3_batch_e.py
- [[TestCronConsistencyCheck]] - code - tests/test_phase3_batch_e.py
- [[consistency_skip must guard the auto_place_trades calls.]] - rationale - tests/test_phase3_batch_e.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_313
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 48]]
- 1 edge to [[_COMMUNITY_Community 312]]

## Top bridge nodes
- [[TestCronConsistencyCheck]] - degree 8, connects to 1 community
- [[dot-test_find_violations_detects_inversion()]] - degree 3, connects to 1 community
- [[dot-test_find_violations_with_clean_markets_returns_empty()]] - degree 3, connects to 1 community