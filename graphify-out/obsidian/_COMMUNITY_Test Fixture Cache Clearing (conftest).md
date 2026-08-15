---
type: community
cohesion: 0.08
members: 39
---

# Test Fixture Cache Clearing (conftest)

**Cohesion:** 0.08 - loosely connected
**Members:** 39 nodes

## Members
- [[Clear config's mtime-gated PAPER_MIN_EDGE cache before every test.…]] - rationale - tests/conftest.py
- [[Default weather_markets._get_ecmwf_aifs_prob to None for every test.…]] - rationale - tests/conftest.py
- [[Default weather_markets._get_gem_ukmo_means to (None, None) for every test.…]] - rationale - tests/conftest.py
- [[Load sample markets from fixture JSON file.]] - rationale - tests/conftest.py
- [[Patch get_weather_forecast to return fixture data.]] - rationale - tests/conftest.py
- [[Redirect circuit_breaker._CB_STATE_PATH to a per-test temp file.…]] - rationale - tests/conftest.py
- [[Redirect climatology.DATA_DIR (used by _cache_path() to build each city's…]] - rationale - tests/conftest.py
- [[Redirect main._CRASH_LOG to a per-test temp file. main.py installs…]] - rationale - tests/conftest.py
- [[Reset all weather_markets, acis_precip, acis_snow, climatology, kalshi_client,…]] - rationale - tests/conftest.py
- [[Snapshot and restore weather_markets._CONDITION_WEIGHTS around every test.…]] - rationale - tests/conftest.py
- [[clear_metar_cache()]] - code - tests/conftest.py
- [[clear_nws_mos_climate_indices_caches()]] - code - tests/conftest.py
- [[clear_paper_min_edge_cache()]] - code - tests/conftest.py
- [[conftest.py]] - code - tests/conftest.py
- [[cron command]] - document - COMMANDS.md
- [[default_ecmwf_aifs_prob_none()]] - code - tests/conftest.py
- [[default_gem_ukmo_means_none()]] - code - tests/conftest.py
- [[fixture]] - code
- [[isolate_circuit_breaker_state fixture]] - code - tests/conftest.py
- [[isolate_climatology_data_dir()]] - code - tests/conftest.py
- [[isolate_climatology_mem_cache()]] - code - tests/conftest.py
- [[isolate_condition_weights()]] - code - tests/conftest.py
- [[isolate_crash_log()]] - code - tests/conftest.py
- [[isolate_cron_generated_files fixture]] - code - tests/conftest.py
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
- [[reset_open_meteo_circuit_breaker fixture]] - code - tests/conftest.py
- [[sample_forecast()]] - code - tests/conftest.py
- [[sample_market()]] - code - tests/conftest.py
- [[sample_markets()]] - code - tests/conftest.py
- [[target_date()]] - code - tests/conftest.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Test_Fixture_Cache_Clearing_conftest
SORT file.name ASC
```

## Connections to other communities
- 29 edges to [[_COMMUNITY_Community 693]]

## Top bridge nodes
- [[conftest.py]] - degree 33, connects to 1 community
- [[fixture]] - degree 30, connects to 1 community
- [[isolate_cron_generated_files fixture]] - degree 5, connects to 1 community
- [[isolate_crash_log()]] - degree 4, connects to 1 community
- [[isolate_retired_strategies()]] - degree 3, connects to 1 community