---
type: community
cohesion: 0.10
members: 20
---

# Community 166

**Cohesion:** 0.10 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-test_sprt_degraded_on_bad_win_rate()]] - code - tests/test_sprt.py
- [[dot-test_sprt_degraded_with_tighter_p1()]] - code - tests/test_sprt.py
- [[dot-test_sprt_insufficient_data()]] - code - tests/test_sprt.py
- [[dot-test_sprt_insufficient_data_with_new_min_trades()]] - code - tests/test_sprt.py
- [[dot-test_sprt_lower_boundary_returns_cleared()]] - code - tests/test_sprt.py
- [[dot-test_sprt_min_trades_default_is_20()]] - code - tests/test_sprt.py
- [[dot-test_sprt_ok_on_good_win_rate()]] - code - tests/test_sprt.py
- [[dot-test_sprt_p1_default_is_0_45()]] - code - tests/test_sprt.py
- [[dot-test_sprt_returns_llr_and_n()]] - code - tests/test_sprt.py
- [[P1-17 15 trades returns insufficient_data with default min_trades=20.]] - rationale - tests/test_sprt.py
- [[P1-17 2950 wins pushes LLR below lower boundary → cleared=True.]] - rationale - tests/test_sprt.py
- [[P1-17 default SPRT_MIN_TRADES is 20 (was 5).]] - rationale - tests/test_sprt.py
- [[P1-17 default SPRT_P1 is 0.45 (was 0.35).]] - rationale - tests/test_sprt.py
- [[P1-17 p1=0.45 fires on moderate degradation that p1=0.35 would miss. 1850 =…]] - rationale - tests/test_sprt.py
- [[Result always contains llr and n keys.]] - rationale - tests/test_sprt.py
- [[Returns 'degraded' when win rate is very low (1050 = 20%).]] - rationale - tests/test_sprt.py
- [[Returns 'ok' when win rate is healthy (3550 = 70%).]] - rationale - tests/test_sprt.py
- [[Returns insufficient_data when fewer than SPRT_MIN_TRADES records exist.]] - rationale - tests/test_sprt.py
- [[TestSprtModelHealth]] - code - tests/test_sprt.py
- [[Tests for tracker.sprt_model_health().]] - rationale - tests/test_sprt.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_166
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 380]]

## Top bridge nodes
- [[TestSprtModelHealth]] - degree 11, connects to 1 community