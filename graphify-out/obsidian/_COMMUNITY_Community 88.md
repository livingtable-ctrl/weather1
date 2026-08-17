---
type: community
cohesion: 0.09
members: 30
---

# Community 88

**Cohesion:** 0.09 - loosely connected
**Members:** 30 nodes

## Members
- [[dot-test_max_temp_at_exact_no_margin_boundary_locks_no()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_at_yes_margin_boundary_locks_yes()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_cleared_upper_edge_with_margin_locks_no()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_inside_band_with_full_clearance_locks_yes()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_just_under_no_margin_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_just_under_yes_margin_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_no_lock_fallback_stays_unlocked_when_current_temp_below_band()]] - code - tests/test_settlement_monitor.py
- [[dot-test_no_lock_falls_back_to_current_temp_when_max_temp_unavailable()]] - code - tests/test_settlement_monitor.py
- [[dot-test_running_high_inside_band_locks_yes_despite_evening_cooling()]] - code - tests/test_settlement_monitor.py
- [[dot-test_running_high_still_below_band_stays_uncertain_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_yes_requires_real_max_temp_not_current_temp_fallback()]] - code - tests/test_settlement_monitor.py
- [[AC3 regression guard, reproducing the entry's own concrete failure scenario…]] - rationale - tests/test_settlement_monitor.py
- [[AC3 regression guard a running high that hasn't reached the band yet must NOT…]] - rationale - tests/test_settlement_monitor.py
- [[AC3 regression guard an in-band INSTANTANEOUS reading alone must never lock…]] - rationale - tests/test_settlement_monitor.py
- [[Determine settlement outcome for a between-bucket market. Returns a dict with…]] - rationale - settlement_monitor.py
- [[Determine settlement outcome for a between-bucket market. Returns a dict with…_1]] - rationale - settlement_monitor.py
- [[TestCheckBetweenSettlement]] - code - tests/test_settlement_monitor.py
- [[TestCheckBetweenSettlement (AC3 between-bucket lockout)]] - code - tests/test_settlement_monitor.py
- [[The exact fallback path the OLD code got wrong max_temp_f unavailable,…]] - rationale - tests/test_settlement_monitor.py
- [[Unit tests for _check_between_settlement (between-bucket lockout logic).…]] - rationale - tests/test_settlement_monitor.py
- [[When max_temp_f is unavailable, the NO direction safely falls back to…]] - rationale - tests/test_settlement_monitor.py
- [[_check_between_settlement()]] - code - settlement_monitor.py
- [[backlog.txt settlement_monitor.py's own between-bucket lock (AC3)]] - document - backlog.txt
- [[max_temp_f 2°F above the upper edge → locked=True, outcome=no.]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f at the lower edge → max clearance to the at-risk upper edge (full…]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f exactly at the NO margin boundary → locks (=, not ). Mutation…]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f exactly at the half-band-width margin → locks (=, not ).]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f just inside the at-risk edge of the margin → not locked.]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f just under the NO margin → not locked.]] - rationale - tests/test_settlement_monitor.py
- [[weather_markets._dynamic_lock_in_confidence()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_88
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 51]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 8]]

## Top bridge nodes
- [[_check_between_settlement()]] - degree 20, connects to 4 communities
- [[TestCheckBetweenSettlement]] - degree 13, connects to 1 community
- [[backlog.txt settlement_monitor.py's own between-bucket lock (AC3)]] - degree 2, connects to 1 community