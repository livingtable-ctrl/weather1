---
type: community
cohesion: 0.20
members: 10
---

# Community 375

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_abtest_default_max_trades_per_variant_is_200()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_abtest_persists_max_trades_to_state()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_default_max_trades_constant_is_200()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_get_active_variant_reads_max_from_state()]] - code - tests/test_phase3_batch_e.py
- [[dot-test_get_active_variant_uses_state_limit_not_module_constant()]] - code - tests/test_phase3_batch_e.py
- [[ABTest.__init__ must write max_trades_per_variant into _meta of the state file.]] - rationale - tests/test_phase3_batch_e.py
- [[P3-2 max_trades_per_variant default must be 200; get_active_variant reads from…]] - rationale - tests/test_phase3_batch_e.py
- [[TestABTestSampleSize]] - code - tests/test_phase3_batch_e.py
- [[Variant with trades  state limit is active even if trades =…]] - rationale - tests/test_phase3_batch_e.py
- [[get_active_variant must honour the max_trades_per_variant stored in state, not…]] - rationale - tests/test_phase3_batch_e.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_375
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[TestABTestSampleSize]] - degree 7, connects to 1 community