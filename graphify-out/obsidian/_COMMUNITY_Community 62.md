---
type: community
cohesion: 0.09
members: 35
---

# Community 62

**Cohesion:** 0.09 - loosely connected
**Members:** 35 nodes

## Members
- [[Derive an ACIS StnData `sid` from metar.MARKET_STATION_MAPcity by stripping…]] - rationale - acis_precip.py
- [[For each historical year present in `history`, sum the remaining_start_day,…]] - rationale - acis_precip.py
- [[GET Open-Meteo Seasonal (monthly=snowfall_mean -- confirmed live 2026-07-30 as…]] - rationale - acis_snow.py
- [[Mirrors weather_markets._bootstrap_ci_precip's exact resampling shape n…]] - rationale - acis_precip.py
- [[NOAA ACIS StnData (month-to-date actual + historical daily precipitation) and…]] - rationale - acis_precip.py
- [[NOAA ACIS StnData (month-to-date actual + historical daily snowfall) and Open-…]] - rationale - acis_snow.py
- [[One POST call covering the full `years`-year daily history, disk- cached so one…]] - rationale - acis_precip.py
- [[One POST call covering the full `years`-year daily snowfall history, disk-…]] - rationale - acis_snow.py
- [[Own copy, not imported from acis_precip that module's version reads…]] - rationale - acis_snow.py
- [[POST to ACIS StnData for sdate=YYYY-MM-01 through through_day (always…]] - rationale - acis_precip.py
- [[POST to ACIS StnData for sdate=YYYY-MM-01 through through_day (always…_1]] - rationale - acis_snow.py
- [[Parse one ACIS 'pcpn' daily value. Returns None for missing unparseable (never…]] - rationale - acis_precip.py
- [[Parse one ACIS 'snow' daily value. Returns None for missing unparseable (never…]] - rationale - acis_snow.py
- [[Path]] - code
- [[Path_1]] - code
- [[Returns (possibly-shifted remaining_sums, tilt_applied). No-ops…]] - rationale - acis_precip.py
- [[_cache_is_stale()]] - code - acis_precip.py
- [[_cache_is_stale()_1]] - code - acis_snow.py
- [[_cache_path()]] - code - acis_precip.py
- [[_cache_path()_1]] - code - acis_snow.py
- [[_load_stale_cache_or_none()]] - code - acis_precip.py
- [[_load_stale_cache_or_none()_1]] - code - acis_snow.py
- [[_parse_pcpn_value()]] - code - acis_precip.py
- [[_parse_snow_value()]] - code - acis_snow.py
- [[_station_sid_for_city()]] - code - acis_precip.py
- [[acis_precip.py]] - code - acis_precip.py
- [[acis_snow.py]] - code - acis_snow.py
- [[apply_seasonal_tilt()]] - code - acis_precip.py
- [[bootstrap_ci_month_total()]] - code - acis_precip.py
- [[fetch_historical_daily()]] - code - acis_precip.py
- [[fetch_historical_daily_snow()]] - code - acis_snow.py
- [[fetch_month_to_date_actual()]] - code - acis_precip.py
- [[fetch_month_to_date_actual_snow()]] - code - acis_snow.py
- [[fetch_seasonal_snow_mean_cm()]] - code - acis_snow.py
- [[historical_remaining_and_full_month_sums()]] - code - acis_precip.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_62
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 4 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 2 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_Community 182]]
- 2 edges to [[_COMMUNITY_Community 51]]
- 2 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 271]]
- 1 edge to [[_COMMUNITY_Community 237]]
- 1 edge to [[_COMMUNITY_Community 174]]

## Top bridge nodes
- [[acis_precip.py]] - degree 23, connects to 9 communities
- [[acis_snow.py]] - degree 22, connects to 8 communities
- [[fetch_historical_daily()]] - degree 8, connects to 2 communities
- [[fetch_historical_daily_snow()]] - degree 8, connects to 2 communities
- [[fetch_seasonal_snow_mean_cm()]] - degree 6, connects to 1 community