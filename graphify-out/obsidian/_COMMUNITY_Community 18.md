---
type: community
cohesion: 0.05
members: 61
---

# Community 18

**Cohesion:** 0.05 - loosely connected
**Members:** 61 nodes

## Members
- [[Clear config's mtime-gated PAPER_MIN_EDGE cache before every test.…]] - rationale - tests/conftest.py
- [[Clear nws.pymos.pyclimate_indices.py's in-process caches before every test,…]] - rationale - tests/conftest.py
- [[Clear the in-process METAR cache(s) before every test. metar._METAR_CACHE is a…]] - rationale - tests/conftest.py
- [[Clear weather_markets' forecastensemble disk-cache pending-write buffers…]] - rationale - tests/conftest.py
- [[Default weather_markets._get_ecmwf_aifs_prob to None for every test.…]] - rationale - tests/conftest.py
- [[Default weather_markets._get_gem_ukmo_means to (None, None) for every test.…]] - rationale - tests/conftest.py
- [[Load sample forecast from fixture JSON file.]] - rationale - tests/conftest.py
- [[Load sample markets from fixture JSON file.]] - rationale - tests/conftest.py
- [[Minimal market dict that passes is_liquid and parse_market_price.]] - rationale - tests/conftest.py
- [[Mock Kalshi API client with sample market data.]] - rationale - tests/conftest.py
- [[Patch get_weather_forecast to return fixture data.]] - rationale - tests/conftest.py
- [[Patch ml_bias._TEMP_CACHE to neutral T=1.0 before every test.…]] - rationale - tests/conftest.py
- [[Patch paper to use a temp data file and start with $1000 balance.]] - rationale - tests/conftest.py
- [[Redirect circuit_breaker's flash-crash historycooldown paths to per-test temp…]] - rationale - tests/conftest.py
- [[Redirect circuit_breaker._CB_STATE_PATH to a per-test temp file.…]] - rationale - tests/conftest.py
- [[Redirect climatology's forecast-sigma cache to a per-test temp file and short-…]] - rationale - tests/conftest.py
- [[Redirect climatology.DATA_DIR (used by _cache_path() to build each city's…]] - rationale - tests/conftest.py
- [[Redirect every production path _cmd_cron_body() (or something it calls) can…]] - rationale - tests/conftest.py
- [[Redirect main._CRASH_LOG to a per-test temp file. main.py installs…]] - rationale - tests/conftest.py
- [[Redirect tracker._RETIRED_PATH to an empty temp file for every test. Prevents…]] - rationale - tests/conftest.py
- [[Redirect weather_markets' forecastensemble disk-cache paths to a per-test temp…]] - rationale - tests/conftest.py
- [[Reset all weather_markets, acis_precip, acis_snow, climatology, kalshi_client,…]] - rationale - tests/conftest.py
- [[Reset climatology._MEM_CACHE (30yr climate archive data, keyed by city) to a…]] - rationale - tests/conftest.py
- [[Set DASHBOARD_UNPROTECTED=true so web_app importsbuilds don't require…]] - rationale - tests/conftest.py
- [[Shared pytest fixtures for the Kalshi weather markets test suite.]] - rationale - tests/conftest.py
- [[Snapshot and restore weather_markets._CONDITION_WEIGHTS around every test.…]] - rationale - tests/conftest.py
- [[Standard mock Kalshi market dict — must stay in sync with production field…]] - rationale - tests/conftest.py
- [[_force_demo_env fixture]] - code - tests/test_web_app.py
- [[_set_dashboard_unprotected()]] - code - tests/conftest.py
- [[clear_metar_cache()]] - code - tests/conftest.py
- [[clear_nws_mos_climate_indices_caches()]] - code - tests/conftest.py
- [[clear_paper_min_edge_cache()]] - code - tests/conftest.py
- [[client fixture]] - code - tests/test_web_app.py
- [[conftest.py]] - code - tests/conftest.py
- [[cron command]] - document - COMMANDS.md
- [[dashboard command]] - document - COMMANDS.md
- [[default_ecmwf_aifs_prob_none()]] - code - tests/conftest.py
- [[default_gem_ukmo_means_none()]] - code - tests/conftest.py
- [[fixture_5]] - code
- [[isolate_circuit_breaker_state()]] - code - tests/conftest.py
- [[isolate_climatology_data_dir()]] - code - tests/conftest.py
- [[isolate_climatology_mem_cache()]] - code - tests/conftest.py
- [[isolate_condition_weights()]] - code - tests/conftest.py
- [[isolate_crash_log()]] - code - tests/conftest.py
- [[isolate_cron_generated_files()]] - code - tests/conftest.py
- [[isolate_dynamic_sigma()]] - code - tests/conftest.py
- [[isolate_flash_crash_cb_state()]] - code - tests/conftest.py
- [[isolate_forecast_ensemble_disk_cache()]] - code - tests/conftest.py
- [[isolate_retired_strategies()]] - code - tests/conftest.py
- [[mock_balance_1000()]] - code - tests/conftest.py
- [[mock_forecast()]] - code - tests/conftest.py
- [[mock_kalshi_client()]] - code - tests/conftest.py
- [[mock_market()]] - code - tests/conftest.py
- [[neutral_temperature_scaling()]] - code - tests/conftest.py
- [[pytest_sessionfinish()]] - code - tests/conftest.py
- [[reset_open_meteo_circuit_breaker()]] - code - tests/conftest.py
- [[sample_forecast()]] - code - tests/conftest.py
- [[sample_market()]] - code - tests/conftest.py
- [[sample_markets()]] - code - tests/conftest.py
- [[target_date()]] - code - tests/conftest.py
- [[web command]] - document - COMMANDS.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_18
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 186]]
- 2 edges to [[_COMMUNITY_Community 338]]
- 2 edges to [[_COMMUNITY_Community 401]]
- 2 edges to [[_COMMUNITY_Community 455]]
- 1 edge to [[_COMMUNITY_Community 0]]

## Top bridge nodes
- [[conftest.py]] - degree 37, connects to 6 communities
- [[fixture_5]] - degree 30, connects to 4 communities