---
type: community
cohesion: 0.08
members: 39
---

# Community 53

**Cohesion:** 0.08 - loosely connected
**Members:** 39 nodes

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
- [[Each market dict has the minimum keys the rest of the system relies on.]] - rationale - tests/test_integration_live.py
- [[Fetching weather markets from demo API returns a non-empty list.]] - rationale - tests/test_integration_live.py
- [[Integration tests for analyze_trade() (112).]] - rationale - tests/test_integration.py
- [[Integration tests for the analyze_trade pipeline (112). Tests verify that…]] - rationale - tests/test_integration.py
- [[Live Kalshi API integration tests. These tests make real network calls to the…]] - rationale - tests/test_integration_live.py
- [[Return a KalshiClient pointed at the demo environment, or skip if not…]] - rationale - tests/test_integration_live.py
- [[TestAnalyzePipeline]] - code - tests/test_integration.py
- [[TestAnalyzePipelineExtra]] - code - tests/test_integration.py
- [[_demo_client()]] - code - tests/test_integration_live.py
- [[_make_enriched()_2]] - code - tests/test_integration.py
- [[analyze_trade handles a LOW market (below condition) correctly.]] - rationale - tests/test_integration.py
- [[analyze_trade raises ValueError for non-dict input.]] - rationale - tests/test_integration.py
- [[analyze_trade returns None when _city is missing.]] - rationale - tests/test_integration.py
- [[analyze_trade returns None when _date is missing.]] - rationale - tests/test_integration.py
- [[analyze_trade returns None when _forecast is missing (no forecast data).]] - rationale - tests/test_integration.py
- [[analyze_trade returns a non-None dict with forecast_prob and edge keys.]] - rationale - tests/test_integration.py
- [[analyze_trade routes precip_any markets through _analyze_precip_trade.]] - rationale - tests/test_integration.py
- [[analyze_trade succeeds even when NWS and climatology return None.]] - rationale - tests/test_integration.py
- [[analyze_trade() returns a non-None result for at least one live market.]] - rationale - tests/test_integration_live.py
- [[date_6]] - code
- [[integration_1]] - code
- [[patch_1]] - code
- [[signal field must be a non-empty string with a recognised prefix (BUY, SELL,…]] - rationale - tests/test_integration.py
- [[test_analyze_trade_returns_dict_for_live_market()]] - code - tests/test_integration_live.py
- [[test_fetch_markets_returns_list()]] - code - tests/test_integration_live.py
- [[test_integration.py]] - code - tests/test_integration.py
- [[test_integration_live.py]] - code - tests/test_integration_live.py
- [[test_market_has_required_fields()]] - code - tests/test_integration_live.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_53
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 52]]

## Top bridge nodes
- [[test_integration_live.py]] - degree 9, connects to 3 communities
- [[test_analyze_trade_returns_dict_for_live_market()]] - degree 6, connects to 2 communities
- [[_demo_client()]] - degree 6, connects to 1 community
- [[test_integration.py]] - degree 6, connects to 1 community
- [[test_fetch_markets_returns_list()]] - degree 5, connects to 1 community