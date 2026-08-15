---
type: community
cohesion: 0.14
members: 17
---

# Community 201

**Cohesion:** 0.14 - loosely connected
**Members:** 17 nodes

## Members
- [[Context manager stack that patches all network calls inside analyze_trade.]] - rationale - tests/test_data_freshness.py
- [[Enriched dict with correct keys; fetched_at controls freshness.]] - rationale - tests/test_data_freshness.py
- [[FORECAST_MAX_AGE_SECS must be a positive integer.]] - rationale - tests/test_data_freshness.py
- [[If data_fetched_at is absent, analyze_trade must not reject the data.]] - rationale - tests/test_data_freshness.py
- [[Tests for P0.3 — FORECAST_MAX_AGE_SECS and stale data rejection in…]] - rationale - tests/test_data_freshness.py
- [[_enriched()]] - code - tests/test_data_freshness.py
- [[_mock_externals()]] - code - tests/test_data_freshness.py
- [[analyze_trade must not reject data when data_fetched_at is recent.]] - rationale - tests/test_data_freshness.py
- [[analyze_trade must return None when data_fetched_at is beyond…]] - rationale - tests/test_data_freshness.py
- [[enrich_with_forecast must add data_fetched_at to the returned dict.]] - rationale - tests/test_data_freshness.py
- [[test_analyze_trade_accepts_fresh_data()]] - code - tests/test_data_freshness.py
- [[test_analyze_trade_no_fetched_at_is_treated_as_fresh()]] - code - tests/test_data_freshness.py
- [[test_analyze_trade_rejects_stale_data()]] - code - tests/test_data_freshness.py
- [[test_data_freshness.py]] - code - tests/test_data_freshness.py
- [[test_enrich_with_forecast_stamps_data_fetched_at()]] - code - tests/test_data_freshness.py
- [[test_forecast_max_age_secs_is_positive_int()]] - code - tests/test_data_freshness.py
- [[weather_markets.FORECAST_MAX_AGE_SECS]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_201
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[test_data_freshness.py]] - degree 12, connects to 2 communities
- [[test_analyze_trade_accepts_fresh_data()]] - degree 4, connects to 1 community
- [[test_analyze_trade_no_fetched_at_is_treated_as_fresh()]] - degree 4, connects to 1 community
- [[test_analyze_trade_rejects_stale_data()]] - degree 4, connects to 1 community
- [[test_enrich_with_forecast_stamps_data_fetched_at()]] - degree 3, connects to 1 community