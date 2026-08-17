---
type: community
cohesion: 0.21
members: 13
---

# Community 282

**Cohesion:** 0.21 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-_mock_perf()]] - code - tests/test_p9_p10.py
- [[dot-test_fails_at_0_24()]] - code - tests/test_p9_p10.py
- [[dot-test_max_brier_default_is_0_23()]] - code - tests/test_p9_p10.py
- [[dot-test_passes_at_0_21()]] - code - tests/test_p9_p10.py
- [[dot-test_passes_at_0_22()]] - code - tests/test_p9_p10.py
- [[dot-test_uses_last_50_brier()]] - code - tests/test_p9_p10.py
- [[Brier=0.21 now passes (previously unreachable under all-time 0.20).]] - rationale - tests/test_p9_p10.py
- [[TestGraduationBrierGate]] - code - tests/test_p9_p10.py
- [[graduation_check() default max_brier threshold must be 0.23.]] - rationale - tests/test_p9_p10.py
- [[graduation_check() must call brier_score(last_n=50), not all-time.]] - rationale - tests/test_p9_p10.py
- [[graduation_check() returns None when last-50 Brier is 0.24  0.23.]] - rationale - tests/test_p9_p10.py
- [[graduation_check() returns a result dict when last-50 Brier is 0.22.]] - rationale - tests/test_p9_p10.py
- [[graduation_check() uses last-50 Brier with threshold 0.23.]] - rationale - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_282
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 54]]

## Top bridge nodes
- [[TestGraduationBrierGate]] - degree 8, connects to 1 community