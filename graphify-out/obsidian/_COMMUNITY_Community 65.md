---
type: community
cohesion: 0.08
members: 34
---

# Community 65

**Cohesion:** 0.08 - loosely connected
**Members:** 34 nodes

## Members
- [[dot-test_boundary_wind_chill_threshold()]] - code - tests/test_weather_markets.py
- [[dot-test_cold_high_humidity_below_actual()]] - code - tests/test_phase4.py
- [[dot-test_cold_low_humidity_no_penalty()]] - code - tests/test_phase4.py
- [[dot-test_cold_windy_returns_lower_than_actual()]] - code - tests/test_weather_markets.py
- [[dot-test_comfortable_no_adjustment()]] - code - tests/test_forecasting.py
- [[dot-test_default_params_used()]] - code - tests/test_weather_markets.py
- [[dot-test_existing_hot_humid_still_works()]] - code - tests/test_phase4.py
- [[dot-test_heat_index_regime()]] - code - tests/test_forecasting.py
- [[dot-test_hot_humid_returns_higher_than_actual()]] - code - tests/test_weather_markets.py
- [[dot-test_moderate_conditions_returns_near_actual()]] - code - tests/test_weather_markets.py
- [[dot-test_moderate_temp_no_moist_cold()]] - code - tests/test_phase4.py
- [[dot-test_moist_cold_no_wind_intermediate()]] - code - tests/test_forecasting.py
- [[dot-test_moist_cold_wind_chill_humidity_penalty()]] - code - tests/test_forecasting.py
- [[dot-test_wind_chill_only()]] - code - tests/test_forecasting.py
- [[55°F with high humidity → no moist-cold penalty (above 50°F threshold).]] - rationale - tests/test_phase4.py
- [[Cold with low humidity and light wind → close to actual (NWS wind chill).]] - rationale - tests/test_phase4.py
- [[Comfortable conditions return raw temp.]] - rationale - tests/test_forecasting.py
- [[Compute apparent (feels-like) temperature from actual temp, wind, and humidity.…]] - rationale - weather_markets.py
- [[Function uses sane defaults (wind_mph=10, humidity_pct=50).]] - rationale - tests/test_weather_markets.py
- [[Heat index should raise apparent temperature above actual.]] - rationale - tests/test_weather_markets.py
- [[Heat index still works for hot+humid conditions.]] - rationale - tests/test_phase4.py
- [[Moderate tempwindhumidity falls through to actual temperature.]] - rationale - tests/test_weather_markets.py
- [[Standard cold+wind, no humidity penalty.]] - rationale - tests/test_forecasting.py
- [[TestFeelsLike]] - code - tests/test_forecasting.py
- [[TestFeelsLike_1]] - code - tests/test_weather_markets.py
- [[TestFeelsLikeMoistCold]] - code - tests/test_phase4.py
- [[Wind chill only applies when temp = 50 and wind = 3 mph.]] - rationale - tests/test_weather_markets.py
- [[Wind chill should lower apparent temperature below actual.]] - rationale - tests/test_weather_markets.py
- [[_feels_like()]] - code - weather_markets.py
- [[pyproject.toml (pytestcoverageruffmypy config)]] - document - pyproject.toml
- [[temp=50, no strong wind, humidity=70 â†’ humidity penalty only.]] - rationale - tests/test_forecasting.py
- [[temp=50, wind=3, humidity=70 â†’ wind chill + humidity penalty.]] - rationale - tests/test_forecasting.py
- [[temp=38, humidity=90 → result  38 (moist-cold penalty).]] - rationale - tests/test_phase4.py
- [[temp=80, humidity=40 â†’ heat index above raw temp.]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_65
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 38]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 11]]
- 2 edges to [[_COMMUNITY_Community 0]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[_feels_like()]] - degree 22, connects to 5 communities
- [[TestFeelsLike]] - degree 7, connects to 2 communities
- [[TestFeelsLike_1]] - degree 7, connects to 1 community
- [[TestFeelsLikeMoistCold]] - degree 5, connects to 1 community