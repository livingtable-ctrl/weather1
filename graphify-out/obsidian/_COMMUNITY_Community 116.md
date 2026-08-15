---
type: community
cohesion: 0.08
members: 25
---

# Community 116

**Cohesion:** 0.08 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-_city()_1]] - code - tests/test_weather_markets.py
- [[dot-test_boston_renamed_high_ticker()]] - code - tests/test_weather_markets.py
- [[dot-test_dallas_full_name_in_ticker_not_la()]] - code - tests/test_weather_markets.py
- [[dot-test_la_as_hyphen_segment_detected()]] - code - tests/test_weather_markets.py
- [[dot-test_la_low_temp_series_detected()]] - code - tests/test_weather_markets.py
- [[dot-test_la_title_detected()]] - code - tests/test_weather_markets.py
- [[dot-test_las_vegas_low_ticker_detected()]] - code - tests/test_weather_markets.py
- [[dot-test_las_vegas_title_detected()]] - code - tests/test_weather_markets.py
- [[dot-test_new_orleans_low_ticker_detected()]] - code - tests/test_weather_markets.py
- [[dot-test_philadelphia_full_name_in_ticker_not_la()]] - code - tests/test_weather_markets.py
- [[dot-test_philadelphia_low_ticker_still_has_t()]] - code - tests/test_weather_markets.py
- [[dot-test_philadelphia_renamed_high_ticker_without_t()]] - code - tests/test_weather_markets.py
- [[Call enrich_with_forecast with a mocked forecast and return _city.]] - rationale - tests/test_weather_markets.py
- [[KXHIGHPHIL (renamed from KXHIGHTPHIL, dropped the 'T') → Philadelphia.]] - rationale - tests/test_weather_markets.py
- [[KXHIGHTBOS (renamed from KXHIGHBOS) → Boston.]] - rationale - tests/test_weather_markets.py
- [[KXLOWLA temperature series → city == 'LA'.]] - rationale - tests/test_weather_markets.py
- [[KXLOWTNOLA → NewOrleans.]] - rationale - tests/test_weather_markets.py
- [[KXLOWTPHIL (unrenamed, still has 'T') → Philadelphia.]] - rationale - tests/test_weather_markets.py
- [[KXRAIN-DALLAS ticker 'DALLAS' contains 'LA' — must be Dallas, not LA.]] - rationale - tests/test_weather_markets.py
- [[KXRAIN-PHILADELPHIA ticker 'PHILA' contains 'LA' — must be Philadelphia.]] - rationale - tests/test_weather_markets.py
- [[L5-B bare 'LA' in ticker_up substring must not misfire on city names that…]] - rationale - tests/test_weather_markets.py
- [[Rain market with '-LA-' segment (KXRAIN-LA-...) → city == 'LA'.]] - rationale - tests/test_weather_markets.py
- [[TestCityDetection]] - code - tests/test_weather_markets.py
- [[las vegas' in title → LasVegas even with a generic ticker.]] - rationale - tests/test_weather_markets.py
- [[los angeles' in title → city == 'LA' even with generic ticker.]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_116
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_Community 102]]
- 2 edges to [[_COMMUNITY_Community 578]]
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_Community 632]]
- 1 edge to [[_COMMUNITY_Community 633]]
- 1 edge to [[_COMMUNITY_Community 634]]
- 1 edge to [[_COMMUNITY_Community 635]]
- 1 edge to [[_COMMUNITY_Community 636]]
- 1 edge to [[_COMMUNITY_Community 637]]

## Top bridge nodes
- [[TestCityDetection]] - degree 23, connects to 9 communities
- [[dot-test_boston_renamed_high_ticker()]] - degree 3, connects to 1 community
- [[dot-test_dallas_full_name_in_ticker_not_la()]] - degree 3, connects to 1 community
- [[dot-test_la_as_hyphen_segment_detected()]] - degree 3, connects to 1 community
- [[dot-test_la_low_temp_series_detected()]] - degree 3, connects to 1 community