---
type: community
cohesion: 0.10
members: 22
---

# Community 140

**Cohesion:** 0.10 - loosely connected
**Members:** 22 nodes

## Members
- [[dot-__init__()_3]] - code - ab_test.py
- [[dot-pick_variant()]] - code - ab_test.py
- [[dot-record_outcome()]] - code - ab_test.py
- [[dot-test_get_active_variant_fallback()]] - code - tests/test_ab_test.py
- [[Any_1]] - code
- [[Convenience load a named test from disk and pick the active variant. Returns…]] - rationale - ab_test.py
- [[L4-A get_active_variant must return the variant value, not None. Previously…]] - rationale - tests/test_ab_test.py
- [[L4-A variant value must round-trip through disk (JSON serializedeserialize).…]] - rationale - tests/test_ab_test.py
- [[Pick an active variant (round-robin among non-disabled, non-exhausted variants).]] - rationale - ab_test.py
- [[Record a trade outcome for the given variant.]] - rationale - ab_test.py
- [[Redirect all ab_test state IO to a temp directory for test isolation.]] - rationale - tests/test_ab_test.py
- [[Tests for ab_test.py — AB experiment framework.]] - rationale - tests/test_ab_test.py
- [[_load_test_state()]] - code - ab_test.py
- [[_patch_ab_dir()]] - code - tests/test_ab_test.py
- [[_save_test_state()]] - code - ab_test.py
- [[ab_test.ABTest]] - code - ab_test.py
- [[fixture]] - code
- [[get_active_variant returns ('control', None) for unknown test name.]] - rationale - tests/test_ab_test.py
- [[get_active_variant()]] - code - ab_test.py
- [[test_ab_test.py]] - code - tests/test_ab_test.py
- [[test_l4a_get_active_variant_returns_value()]] - code - tests/test_ab_test.py
- [[test_l4a_get_active_variant_value_survives_reload()]] - code - tests/test_ab_test.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_140
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 116]]
- 5 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[test_ab_test.py]] - degree 11, connects to 4 communities
- [[get_active_variant()]] - degree 10, connects to 2 communities
- [[_load_test_state()]] - degree 4, connects to 2 communities
- [[dot-__init__()_3]] - degree 4, connects to 1 community
- [[test_l4a_get_active_variant_returns_value()]] - degree 4, connects to 1 community