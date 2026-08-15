---
type: community
cohesion: 0.22
members: 9
---

# Community 407

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_all_cities_have_station()]] - code - tests/test_phase4.py
- [[dot-test_chicago_coords_closer_to_kmdw_than_kord()]] - code - tests/test_phase4.py
- [[dot-test_chicago_station_is_kmdw()]] - code - tests/test_phase4.py
- [[dot-test_station_ids_are_icao_format()]] - code - tests/test_phase4.py
- [[All station IDs are 4-character ICAO codes starting with K.]] - rationale - tests/test_phase4.py
- [[CITY_COORDS Chicago must be near Midway (KMDW), not O'Hare (KORD). Kalshi…]] - rationale - tests/test_phase4.py
- [[Chicago must map to Midway (KMDW) — confirmed from Kalshi series API…]] - rationale - tests/test_phase4.py
- [[Every city in CITY_COORDS has a station mapping.]] - rationale - tests/test_phase4.py
- [[TestMarketStationMap]] - code - tests/test_phase4.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_407
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]

## Top bridge nodes
- [[TestMarketStationMap]] - degree 5, connects to 1 community