---
type: community
cohesion: 0.12
members: 16
---

# Community 217

**Cohesion:** 0.12 - loosely connected
**Members:** 16 nodes

## Members
- [[A 5.5% edge (above PAPER_MIN_EDGE, below old MIN_EDGE) must not be filtered.]] - rationale - tests/test_edge_threshold.py
- [[Confirm 5.5% edge is below the old MIN_EDGE (7%) so the distinction matters.]] - rationale - tests/test_edge_threshold.py
- [[Miami requires 20pp probability-edge conviction (vs 8pp default), per the…]] - rationale - tests/test_edge_threshold.py
- [[Mirrors cron.py's `_city_min = CITY_MIN_PROB_EDGE.get(_city_key,…]] - rationale - tests/test_edge_threshold.py
- [[Paper threshold must be lower than the displaylive threshold.]] - rationale - tests/test_edge_threshold.py
- [[Tests for P1.3 — PAPER_MIN_EDGE (via get_paper_min_edge()) and cmd_cron filter.]] - rationale - tests/test_edge_threshold.py
- [[get_paper_min_edge() must be = 5% per system requirements.]] - rationale - tests/test_edge_threshold.py
- [[get_paper_min_edge() must be  0 — zero threshold would trade everything.]] - rationale - tests/test_edge_threshold.py
- [[test_city_min_prob_edge_gate_mirrors_cron_lookup()]] - code - tests/test_edge_threshold.py
- [[test_city_min_prob_edge_miami_override()]] - code - tests/test_edge_threshold.py
- [[test_edge_threshold.py]] - code - tests/test_edge_threshold.py
- [[test_old_min_edge_would_have_blocked_5pct()]] - code - tests/test_edge_threshold.py
- [[test_paper_min_edge_5pct_passes_filter()]] - code - tests/test_edge_threshold.py
- [[test_paper_min_edge_is_at_most_5_pct()]] - code - tests/test_edge_threshold.py
- [[test_paper_min_edge_is_lower_than_min_edge()]] - code - tests/test_edge_threshold.py
- [[test_paper_min_edge_is_positive()]] - code - tests/test_edge_threshold.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_217
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 26]]

## Top bridge nodes
- [[test_edge_threshold.py]] - degree 10, connects to 2 communities
- [[test_paper_min_edge_5pct_passes_filter()]] - degree 3, connects to 1 community
- [[test_paper_min_edge_is_at_most_5_pct()]] - degree 3, connects to 1 community
- [[test_paper_min_edge_is_lower_than_min_edge()]] - degree 3, connects to 1 community
- [[test_paper_min_edge_is_positive()]] - degree 3, connects to 1 community