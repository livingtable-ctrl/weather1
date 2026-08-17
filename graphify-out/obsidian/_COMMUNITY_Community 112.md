---
type: community
cohesion: 0.11
members: 26
---

# Community 112

**Cohesion:** 0.11 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-test_analyze_trade_below_condition()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_handles_missing_forecast()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_invalid_input_raises()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_missing_city_returns_none()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_missing_date_returns_none()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_precip_any_condition()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_returns_result()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_signal_is_valid()]] - code - tests/test_integration.py
- [[dot-test_analyze_trade_works_without_nws_or_clim()]] - code - tests/test_integration.py
- [[Additional integration tests for below + precip conditions (112).]] - rationale - tests/test_integration.py
- [[Build a minimal enriched market dict as produced by enrich_market().]] - rationale - tests/test_integration.py
- [[Integration tests for analyze_trade() (112).]] - rationale - tests/test_integration.py
- [[TestAnalyzePipeline]] - code - tests/test_integration.py
- [[TestAnalyzePipelineExtra]] - code - tests/test_integration.py
- [[_make_enriched()]] - code - tests/test_integration.py
- [[analyze_trade handles a LOW market (below condition) correctly.]] - rationale - tests/test_integration.py
- [[analyze_trade raises ValueError for non-dict input.]] - rationale - tests/test_integration.py
- [[analyze_trade returns None when _city is missing.]] - rationale - tests/test_integration.py
- [[analyze_trade returns None when _date is missing.]] - rationale - tests/test_integration.py
- [[analyze_trade returns None when _forecast is missing (no forecast data).]] - rationale - tests/test_integration.py
- [[analyze_trade returns a non-None dict with forecast_prob and edge keys.]] - rationale - tests/test_integration.py
- [[analyze_trade routes precip_any markets through _analyze_precip_trade.]] - rationale - tests/test_integration.py
- [[analyze_trade succeeds even when NWS and climatology return None.]] - rationale - tests/test_integration.py
- [[date_2]] - code
- [[patch]] - code
- [[signal field must be a non-empty string with a recognised prefix (BUY, SELL,…]] - rationale - tests/test_integration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_112
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 5]]
- 3 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[_make_enriched()]] - degree 11, connects to 1 community
- [[TestAnalyzePipeline]] - degree 8, connects to 1 community
- [[dot-test_analyze_trade_handles_missing_forecast()]] - degree 5, connects to 1 community
- [[dot-test_analyze_trade_returns_result()]] - degree 5, connects to 1 community
- [[dot-test_analyze_trade_works_without_nws_or_clim()]] - degree 5, connects to 1 community