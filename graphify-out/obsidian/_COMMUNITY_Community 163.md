---
type: community
cohesion: 0.12
members: 20
---

# Community 163

**Cohesion:** 0.12 - loosely connected
**Members:** 20 nodes

## Members
- [[A 5.5% edge (above PAPER_MIN_EDGE, below old MIN_EDGE) must not be filtered.]] - rationale - tests/test_edge_threshold.py
- [[Confirm 5.5% edge is below the old MIN_EDGE (7%) so the distinction matters.]] - rationale - tests/test_edge_threshold.py
- [[Live-refreshed PAPER_MIN_EDGE — call this, not a frozen import, from any long-…]] - rationale - utils.py
- [[Miami requires 20pp probability-edge conviction (vs 8pp default), per the…]] - rationale - tests/test_edge_threshold.py
- [[Mirrors cron.py's `_city_min = CITY_MIN_PROB_EDGE.get(_city_key,…]] - rationale - tests/test_edge_threshold.py
- [[Paper threshold must be lower than the displaylive threshold.]] - rationale - tests/test_edge_threshold.py
- [[Tests for P1.3 — PAPER_MIN_EDGE (via get_paper_min_edge()) and cmd_cron filter.]] - rationale - tests/test_edge_threshold.py
- [[get_paper_min_edge()]] - code - utils.py
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
- [[utils.CITY_MIN_PROB_EDGE]] - code - utils.py
- [[utils.MIN_EDGE]] - code - utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_163
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 0]]
- 2 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 76]]
- 1 edge to [[_COMMUNITY_Community 25]]
- 1 edge to [[_COMMUNITY_Community 426]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 17]]
- 1 edge to [[_COMMUNITY_Community 33]]

## Top bridge nodes
- [[get_paper_min_edge()]] - degree 17, connects to 8 communities
- [[test_edge_threshold.py]] - degree 12, connects to 1 community