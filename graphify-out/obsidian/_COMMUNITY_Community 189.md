---
type: community
cohesion: 0.15
members: 18
---

# Community 189

**Cohesion:** 0.15 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-test_date_sold_differs_from_date_acquired()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_date_sold_uses_settled_at()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_december_trade_absent_from_entry_year()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_december_trade_appears_in_settlement_year()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_history_is_sorted_by_ts()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_settlement_event_not_entered_at_with_z_suffix()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_settlement_event_uses_settled_at()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_settlement_fallback_when_no_settled_at()]] - code - tests/test_phase2_batch_i.py
- [[After re-sort, history ts values must be non-decreasing.]] - rationale - tests/test_phase2_batch_i.py
- [[Old records without settled_at must not crash; ts falls back to entered_at.]] - rationale - tests/test_phase2_batch_i.py
- [[Settlement events must use settled_at, not entered_at.]] - rationale - tests/test_phase2_batch_i.py
- [[Tax year filter and Date Sold must use settled_at, not entered_at.]] - rationale - tests/test_phase2_batch_i.py
- [[TestExportTaxCsvSettlementYear]] - code - tests/test_phase2_batch_i.py
- [[TestGetBalanceHistorySettlementTs]] - code - tests/test_phase2_batch_i.py
- [[Trade entered Dec 2025, settled Jan 2026 → must NOT appear in tax_year=2025.]] - rationale - tests/test_phase2_batch_i.py
- [[Trade entered Dec 2025, settled Jan 2026 → must appear in tax_year=2026.]] - rationale - tests/test_phase2_batch_i.py
- [[When entry and settlement are on different dates, Date Sold != Date Acquired.]] - rationale - tests/test_phase2_batch_i.py
- [[_settled_trade()]] - code - tests/test_phase2_batch_i.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_189
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]

## Top bridge nodes
- [[_settled_trade()]] - degree 9, connects to 1 community
- [[TestExportTaxCsvSettlementYear]] - degree 6, connects to 1 community
- [[TestGetBalanceHistorySettlementTs]] - degree 6, connects to 1 community