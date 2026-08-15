---
type: community
cohesion: 0.17
members: 12
---

# Community 311

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-test_fetch_exception_returns_false_not_raise()]] - code - tests/test_rain_markets.py
- [[dot-test_finalized_writes_settled_value_not_settled_var()]] - code - tests/test_rain_markets.py
- [[dot-test_missing_expiration_value_returns_false()]] - code - tests/test_rain_markets.py
- [[dot-test_no_matching_outcomes_row_returns_false()]] - code - tests/test_rain_markets.py
- [[dot-test_non_numeric_expiration_value_returns_false()]] - code - tests/test_rain_markets.py
- [[dot-test_not_finalized_returns_false_no_write()]] - code - tests/test_rain_markets.py
- [[dot-test_rain_branch_reached_before_parse_city_date_early_return()]] - code - tests/test_rain_markets.py
- [[A market with a VALID expiration_value but status != 'finalized' must still be…]] - rationale - tests/test_rain_markets.py
- [[Review-caught gap the UPDATE could match zero rows (no prior outcomes row for…]] - rationale - tests/test_rain_markets.py
- [[TestAuditSettlementMonthlyRain]] - code - tests/test_rain_markets.py
- [[The real regression this fix targets parse_city_date() returns (city, None)…]] - rationale - tests/test_rain_markets.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 handoff item 5…]] - rationale - tests/test_rain_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_311
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 237]]

## Top bridge nodes
- [[TestAuditSettlementMonthlyRain]] - degree 9, connects to 1 community