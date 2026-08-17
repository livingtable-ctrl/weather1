---
type: community
cohesion: 0.22
members: 11
---

# Community 352

**Cohesion:** 0.22 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-_make_enriched()_3]] - code - tests/test_trade_improvements.py
- [[dot-test_cron_imports_min_prob_edge()]] - code - tests/test_trade_improvements.py
- [[dot-test_low_prob_edge_signal_skipped()]] - code - tests/test_trade_improvements.py
- [[dot-test_min_prob_edge_constant_exists()]] - code - tests/test_trade_improvements.py
- [[dot-test_sufficient_prob_edge_signal_passes()]] - code - tests/test_trade_improvements.py
- [[MIN_PROB_EDGE constant must be defined in utils.py with value 0.08.]] - rationale - tests/test_trade_improvements.py
- [[Signal with 12pp probability edge must NOT be skipped by the gate.]] - rationale - tests/test_trade_improvements.py
- [[Signal with only 5pp probability edge must be skipped by the gate.]] - rationale - tests/test_trade_improvements.py
- [[TestMinProbEdgeGate]] - code - tests/test_trade_improvements.py
- [[The prob-edge gate (MIN_PROB_EDGE) must be wired into the module that actually…]] - rationale - tests/test_trade_improvements.py
- [[cron.py must skip signals where probability edge  MIN_PROB_EDGE (0.08).]] - rationale - tests/test_trade_improvements.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_352
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestMinProbEdgeGate]] - degree 7, connects to 1 community