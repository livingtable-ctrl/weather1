---
type: community
cohesion: 0.12
members: 17
---

# Community 205

**Cohesion:** 0.12 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-test_all_cities_return_station()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_city_tz_covers_all_cities()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_city_tz_values_are_valid_iana()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_every_city_coords_entry_has_tz_and_station()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_old_abbreviations_removed()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_settlement_monitor_series_tickers_match_known_weather_series()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_settlement_monitor_stations_match_metar_module()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_station_ids_are_correct()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_station_map_matches_metar_module()]] - code - tests/test_phase2_batch_j.py
- [[All 18 Kalshi cities must map to a METAR station and timezone.]] - rationale - tests/test_phase2_batch_j.py
- [[All timezone strings must be parseable by zoneinfo.]] - rationale - tests/test_phase2_batch_j.py
- [[Every CITY_COORDS key must have a _CITY_TZ and metar.MARKET_STATION_MAP entry…]] - rationale - tests/test_phase2_batch_j.py
- [[Old 3-letter keys (MIA, CHI, LAX, DAL, DEN) must no longer be primary keys.]] - rationale - tests/test_phase2_batch_j.py
- [[TestMetarStationForCityAllCities]] - code - tests/test_phase2_batch_j.py
- [[_CITY_METAR_STATION must agree with metar.MARKET_STATION_MAP.]] - rationale - tests/test_phase2_batch_j.py
- [[_CITY_SERIES_TICKER is now derived from KNOWN_WEATHER_SERIES +…]] - rationale - tests/test_phase2_batch_j.py
- [[settlement_monitor._MONITOR_CITIES is now derived from metar.MARKET_STATION_MAP…]] - rationale - tests/test_phase2_batch_j.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_205
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]

## Top bridge nodes
- [[TestMetarStationForCityAllCities]] - degree 11, connects to 1 community