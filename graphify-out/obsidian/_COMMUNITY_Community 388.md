---
type: community
cohesion: 0.17
members: 9
---

# Community 388

**Cohesion:** 0.17 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_stale_known_weather_series_raises_at_import()_1]] - code - tests/test_settlement_monitor.py
- [[TestCitySeriesTickerDerivation]] - code - tests/test_settlement_monitor.py
- [[_CITY_SERIES_TICKER is derived from KNOWN_WEATHER_SERIES at import time…]] - rationale - tests/test_settlement_monitor.py
- [[_MONITOR_CITIES map]] - code - settlement_monitor.py
- [[_SHORT_CODE_TO_CITY map]] - code - settlement_monitor.py
- [[_validate_trade_opportunity Function]] - code - order_executor.py
- [[_ws_listener Function]] - code - kalshi_ws.py
- [[get_cached_mid_price Function]] - code - kalshi_ws.py
- [[metar.MARKET_STATION_MAP]] - code - metar.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_388
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 160]]

## Top bridge nodes
- [[_MONITOR_CITIES map]] - degree 4, connects to 3 communities
- [[get_cached_mid_price Function]] - degree 3, connects to 1 community
- [[metar.MARKET_STATION_MAP]] - degree 3, connects to 1 community
- [[TestCitySeriesTickerDerivation]] - degree 2, connects to 1 community