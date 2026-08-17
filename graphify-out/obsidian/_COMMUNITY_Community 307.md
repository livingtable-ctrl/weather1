---
type: community
cohesion: 0.17
members: 12
---

# Community 307

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[No exception when ENABLE_MICRO_LIVE is not 'true' (gate is skipped entirely).]] - rationale - tests/test_graduation_gate.py
- [[No exception when ENABLE_MICRO_LIVE='false'.]] - rationale - tests/test_graduation_gate.py
- [[No exception when ENABLE_MICRO_LIVE=true and count = MIN_BRIER_SAMPLES.]] - rationale - tests/test_graduation_gate.py
- [[P2-D Gate must fail-closed when the tracker DB is unavailable. If…]] - rationale - tests/test_graduation_gate.py
- [[RuntimeError raised when ENABLE_MICRO_LIVE=true and count  MIN_BRIER_SAMPLES.]] - rationale - tests/test_graduation_gate.py
- [[Tests for the graduation gate in main.py (_check_graduation_gate).]] - rationale - tests/test_graduation_gate.py
- [[test_gate_fails_closed_when_db_unavailable()]] - code - tests/test_graduation_gate.py
- [[test_gate_passes_when_micro_live_and_sufficient_samples()]] - code - tests/test_graduation_gate.py
- [[test_gate_raises_when_micro_live_and_insufficient_samples()]] - code - tests/test_graduation_gate.py
- [[test_gate_skipped_when_micro_live_explicitly_false()]] - code - tests/test_graduation_gate.py
- [[test_gate_skipped_when_micro_live_false()]] - code - tests/test_graduation_gate.py
- [[test_graduation_gate.py]] - code - tests/test_graduation_gate.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_307
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[test_graduation_gate.py]] - degree 8, connects to 2 communities