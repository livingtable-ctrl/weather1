---
type: community
cohesion: 0.18
members: 11
---

# Community 345

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_default_max_trades_still_works()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_get_active_variant_skips_meta_key()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_get_active_variant_uses_persisted_max()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_meta_key_written_on_init()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_meta_updated_when_max_trades_changes()]] - code - tests/test_phase2_batch_m.py
- [[ABTest.__init__ must write max_trades_per_variant into _meta.]] - rationale - tests/test_phase2_batch_m.py
- [[Constructing ABTest with a new max_trades must update the persisted _meta.]] - rationale - tests/test_phase2_batch_m.py
- [[TestAbTestMaxTradesMeta]] - code - tests/test_phase2_batch_m.py
- [[Without a persisted _meta, _DEFAULT_MAX_TRADES is used.]] - rationale - tests/test_phase2_batch_m.py
- [[get_active_variant must not treat _meta as a variant.]] - rationale - tests/test_phase2_batch_m.py
- [[get_active_variant must respect the persisted max_trades, not…]] - rationale - tests/test_phase2_batch_m.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_345
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 32]]

## Top bridge nodes
- [[TestAbTestMaxTradesMeta]] - degree 7, connects to 2 communities