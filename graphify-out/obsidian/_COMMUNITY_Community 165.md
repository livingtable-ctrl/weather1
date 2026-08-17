---
type: community
cohesion: 0.14
members: 20
---

# Community 165

**Cohesion:** 0.14 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-setUp()_7]] - code - tests/test_http.py
- [[dot-tearDown()_7]] - code - tests/test_http.py
- [[dot-test_all_models_fail_returns_none()]] - code - tests/test_http.py
- [[dot-test_dead_model_all_null_response_treated_as_failure()]] - code - tests/test_http.py
- [[dot-test_partial_model_failure_still_returns()]] - code - tests/test_http.py
- [[dot-test_returns_forecast_when_all_models_respond()]] - code - tests/test_http.py
- [[dot-test_returns_none_when_target_date_missing()]] - code - tests/test_http.py
- [[dot-test_unknown_city_returns_none()]] - code - tests/test_http.py
- [[A dead model returns HTTP 200 with every value null — this must be treated…]] - rationale - tests/test_http.py
- [[All three models respond — forecast should average their values.]] - rationale - tests/test_http.py
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
TABLE source_file, type FROM #community/Community_165
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 26]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[test_http.py]] - degree 8, connects to 4 communities
- [[dot-test_dead_model_all_null_response_treated_as_failure()]] - degree 5, connects to 1 community
- [[dot-test_partial_model_failure_still_returns()]] - degree 5, connects to 1 community
- [[dot-test_returns_forecast_when_all_models_respond()]] - degree 5, connects to 1 community
- [[dot-test_returns_none_when_target_date_missing()]] - degree 5, connects to 1 community