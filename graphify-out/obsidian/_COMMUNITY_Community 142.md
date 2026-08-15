---
type: community
cohesion: 0.13
members: 21
---

# Community 142

**Cohesion:** 0.13 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-setUp()_3]] - code - tests/test_http.py
- [[dot-tearDown()_3]] - code - tests/test_http.py
- [[dot-test_all_models_fail_returns_none()]] - code - tests/test_http.py
- [[dot-test_dead_model_all_null_response_treated_as_failure()]] - code - tests/test_http.py
- [[dot-test_partial_model_failure_still_returns()]] - code - tests/test_http.py
- [[dot-test_returns_forecast_when_all_models_respond()]] - code - tests/test_http.py
- [[dot-test_returns_none_when_target_date_missing()]] - code - tests/test_http.py
- [[dot-test_unknown_city_returns_none()]] - code - tests/test_http.py
- [[A dead model returns HTTP 200 with every value null — this must be treated…]] - rationale - tests/test_http.py
- [[All three models respond — forecast should average their values.]] - rationale - tests/test_http.py
- [[Grade Audit Module Doc kalshi_client.py]] - document - docs/grade_audit/modules/kalshi_client.md
- [[HTTP integration tests using `responses` to mock Open-Meteo API calls. These…]] - rationale - tests/test_http.py
- [[If every model call fails, return None.]] - rationale - tests/test_http.py
- [[If one model returns data for the wrong date, we still get a result from the…]] - rationale - tests/test_http.py
- [[If the API doesn't include our target date, return None.]] - rationale - tests/test_http.py
- [[Minimal Open-Meteo daily response.]] - rationale - tests/test_http.py
- [[TestGetWeatherForecastMocked]] - code - tests/test_http.py
- [[Unknown city should return None without making any HTTP calls.]] - rationale - tests/test_http.py
- [[_open_meteo_payload()]] - code - tests/test_http.py
- [[activate]] - code
- [[test_http.py]] - code - tests/test_http.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_142
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 143]]
- 1 edge to [[_COMMUNITY_Community 225]]
- 1 edge to [[_COMMUNITY_Community 351]]
- 1 edge to [[_COMMUNITY_Community 180]]

## Top bridge nodes
- [[Grade Audit Module Doc kalshi_client.py]] - degree 5, connects to 4 communities
- [[test_http.py]] - degree 7, connects to 3 communities
- [[dot-test_dead_model_all_null_response_treated_as_failure()]] - degree 5, connects to 1 community
- [[dot-test_partial_model_failure_still_returns()]] - degree 5, connects to 1 community
- [[dot-test_returns_forecast_when_all_models_respond()]] - degree 5, connects to 1 community