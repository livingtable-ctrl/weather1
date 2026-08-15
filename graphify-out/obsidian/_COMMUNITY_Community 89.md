---
type: community
cohesion: 0.10
members: 28
---

# Community 89

**Cohesion:** 0.10 - loosely connected
**Members:** 28 nodes

## Members
- [[Every CITY_COORDS city must have at least one working ticker in…]] - rationale - tests/test_city_registry_manifest.py
- [[Guard test for the per-city registry completeness manifest (backlog.txt PER-…]] - rationale - tests/test_city_registry_manifest.py
- [[Per-city completeness manifest across the per-city registries a tradeable city…]] - rationale - weather_markets.py
- [[Registry 9 (backlog.txt NWS AFD PARSING  PER-CITY KNOWLEDGE SCATTERED) --…]] - rationale - tests/test_city_registry_manifest.py
- [[Regression guard for a real bug found by opus review on the 2026-07-26 St.…]] - rationale - tests/test_city_registry_manifest.py
- [[Regression guard for the 2026-07-26 series_ticker generalization (was KXHIGH-…]] - rationale - tests/test_city_registry_manifest.py
- [[Same isolation contract as check_series_drift -- a corrupted state file must…]] - rationale - tests/test_city_registry_report_logging.py
- [[Sanity check on the manifest itself, independent of the allowlist below --…]] - rationale - tests/test_city_registry_manifest.py
- [[Second call the same day must be a no-op -- proven by checking the state file's…]] - rationale - tests/test_city_registry_report_logging.py
- [[Tests for log_city_registry_report() — once-per-day logging wrapper around…]] - rationale - tests/test_city_registry_report_logging.py
- [[The inverse check if a _KNOWN_GAPS entry no longer reflects a real gap…]] - rationale - tests/test_city_registry_manifest.py
- [[_today()]] - code - tests/test_city_registry_report_logging.py
- [[city_registry_report()]] - code - weather_markets.py
- [[test_city_registry_manifest.py]] - code - tests/test_city_registry_manifest.py
- [[test_city_registry_report_logging.py]] - code - tests/test_city_registry_report_logging.py
- [[test_first_run_creates_state_file()]] - code - tests/test_city_registry_report_logging.py
- [[test_gated_to_run_once_per_day()]] - code - tests/test_city_registry_report_logging.py
- [[test_known_gaps_are_still_actually_gaps()]] - code - tests/test_city_registry_manifest.py
- [[test_metar_station_fully_covered()]] - code - tests/test_city_registry_manifest.py
- [[test_never_raises_on_a_broken_state_file()]] - code - tests/test_city_registry_report_logging.py
- [[test_no_new_unexplained_registry_gaps()]] - code - tests/test_city_registry_manifest.py
- [[test_report_covers_all_city_coords_cities()]] - code - tests/test_city_registry_manifest.py
- [[test_runs_again_on_a_new_day()]] - code - tests/test_city_registry_report_logging.py
- [[test_series_ticker_fully_covered()]] - code - tests/test_city_registry_manifest.py
- [[test_st_petersburg_series_ticker_comes_from_rain_not_high()]] - code - tests/test_city_registry_manifest.py
- [[test_station_bias_fully_covered()]] - code - tests/test_city_registry_manifest.py
- [[test_temperature_market_cities_excludes_rain_only_cities()]] - code - tests/test_city_registry_manifest.py
- [[test_wfo_office_fully_covered()]] - code - tests/test_city_registry_manifest.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_89
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[test_city_registry_manifest.py]] - degree 16, connects to 3 communities
- [[city_registry_report()]] - degree 14, connects to 2 communities
- [[test_city_registry_report_logging.py]] - degree 9, connects to 1 community