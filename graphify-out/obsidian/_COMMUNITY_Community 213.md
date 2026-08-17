---
type: community
cohesion: 0.17
members: 17
---

# Community 213

**Cohesion:** 0.17 - loosely connected
**Members:** 17 nodes

## Members
- [[(city, _CITY_TZ value) pairs for the 4 representative US timezones this bot…]] - rationale - tests/test_weather_markets.py
- [[dot-_enriched()_4]] - code - tests/test_weather_markets.py
- [[dot-now()]] - code - tests/test_weather_markets.py
- [[dot-test_days_out_ceiling_uses_city_local_today_not_utc()]] - code - tests/test_weather_markets.py
- [[dot-test_genuinely_past_market_still_gated_during_utc_rollover_window()]] - code - tests/test_weather_markets.py
- [[dot-test_same_day_market_still_open_during_utc_rollover_window()]] - code - tests/test_weather_markets.py
- [[dot-test_still_open_local_market_hits_forecast_not_timemachine()]] - code - tests/test_weather_markets.py
- [[A market that is genuinely one full day in the past for the city (not just UTC)…]] - rationale - tests/test_weather_markets.py
- [[A market whose target_date is still today in the city's own timezone must NOT…]] - rationale - tests/test_weather_markets.py
- [[TestFetchTemperaturePirateWeatherHistoricalRouting]] - code - tests/test_weather_markets.py
- [[TestPastDateGateCityLocal]] - code - tests/test_weather_markets.py
- [[The generic days_out ceiling gate (MAX_DAYS_OUT) must also key off city-local…]] - rationale - tests/test_weather_markets.py
- [[_FrozenDatetime]] - code - tests/test_weather_markets.py
- [[_frozen_datetime_at()]] - code - tests/test_weather_markets.py
- [[datetime_1]] - code
- [[datetime.now(tz) returns _FROZEN_INSTANT converted to tz (or naive…]] - rationale - tests/test_weather_markets.py
- [[fetch_temperature_pirate_weather must route to the FORECAST endpoint (not the…]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_213
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 11]]
- 3 edges to [[_COMMUNITY_Community 53]]

## Top bridge nodes
- [[datetime_1]] - degree 6, connects to 1 community
- [[TestPastDateGateCityLocal]] - degree 6, connects to 1 community
- [[dot-test_days_out_ceiling_uses_city_local_today_not_utc()]] - degree 6, connects to 1 community
- [[dot-test_genuinely_past_market_still_gated_during_utc_rollover_window()]] - degree 6, connects to 1 community
- [[dot-test_same_day_market_still_open_during_utc_rollover_window()]] - degree 6, connects to 1 community