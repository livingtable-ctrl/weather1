---
type: community
cohesion: 0.05
members: 63
---

# NWS/Circuit-Breaker Data Validation

**Cohesion:** 0.05 - loosely connected
**Members:** 63 nodes

## Members
- [[106107 Configure structured logging. Each module should use…]] - rationale - utils.py
- [[dot-test_partial_data_high_only()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_high_low_dict()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_when_date_missing()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_when_nws_unavailable()]] - code - tests/test_weather_markets.py
- [[BotConfig.validate() Missing Threshold Guards (510)]] - document - docs/grade_audit/outputs/config.py.md
- [[Convert NWS forecast temperature to a probability using a narrow normal…]] - rationale - nws.py
- [[Fetch NWS official daily highlow forecast for a city. Returns dict keyed by…]] - rationale - nws.py
- [[Fetch the latest hourly observation for a city. Returns dict with temp_f,…]] - rationale - nws.py
- [[Fetch the latest observed precipitation (inches) from NWS for same-day markets.…]] - rationale - nws.py
- [[I5 Kelly FiniteRange Guard]] - document - docs/grade_audit/outputs
- [[Load persisted station cache from disk into _station_cache (best-effort).]] - rationale - nws.py
- [[Lock]] - code
- [[Logger]] - code
- [[Missing EXECUTION_LOG_PATH Centralization (Possible)]] - document - docs/grade_audit/outputs/paths.py.md
- [[NOAA National Weather Service API integration. Provides - Official calibrated…]] - rationale - nws.py
- [[No _DATA.is_dir() Guard at Import Time]] - document - docs/grade_audit/outputs/paths.py.md
- [[Persist station cache to disk (best-effort, never raises).]] - rationale - nws.py
- [[RF6 No Test Coverage on Trade Path]] - document - docs/grade_audit/outputs
- [[Return (creating if needed) the per-city observation lock.]] - rationale - nws.py
- [[Return NBM highlow for a specific date via the NWS gridpoints API. NBM…]] - rationale - nws.py
- [[Shared utilities used across the Kalshi weather trading modules.]] - rationale - utils.py
- [[Simple per-source circuit breaker. States CLOSED — normal operation OPEN —…]] - rationale - circuit_breaker.py
- [[Single source of truth for all data and state file paths. Import from here…]] - rationale - paths.py
- [[TestFetchNbmForecast]] - code - tests/test_weather_markets.py
- [[Validate NWS API point forecast response.]] - rationale - schema_validator.py
- [[Validate a forecastweather API response dict. Returns True if valid, False if…]] - rationale - schema_validator.py
- [[_get with a hard wall-clock deadline for observation endpoints. Windows SSL can…]] - rationale - nws.py
- [[_get()]] - code - nws.py
- [[_get_gridpoint()]] - code - nws.py
- [[_get_obs()]] - code - nws.py
- [[_get_obs_lock()]] - code - nws.py
- [[_get_obs_station()]] - code - nws.py
- [[_hash_fingerprint()]] - code - utils.py
- [[_load_station_cache()]] - code - nws.py
- [[_place_live_order() KeyError Risk max_open_positions (710)]] - document - docs/grade_audit/outputs/order_executor.py.md
- [[_save_station_cache()]] - code - nws.py
- [[_setup_logging()]] - code - utils.py
- [[_station_key_to_str()]] - code - nws.py
- [[_station_str_to_key()]] - code - nws.py
- [[check_edge.py]] - code - check_edge.py
- [[circuit_breaker.py]] - code - circuit_breaker.py
- [[date]] - code
- [[detect_regime() RF6 Zero Test Coverage on Live Kelly Path (510)]] - document - docs/grade_audit/outputs/regime.py.md
- [[fetch_nbm_forecast()]] - code - nws.py
- [[fetch_nbm_forecast() wraps get_nws_daily_forecast() into a flat dict.]] - rationale - tests/test_weather_markets.py
- [[get_live_observation()]] - code - nws.py
- [[get_live_precip_obs()]] - code - nws.py
- [[get_nws_daily_forecast()]] - code - nws.py
- [[nws.py]] - code - nws.py
- [[nws.py File Grade well-structured, 1 RF1 finding]] - document - docs/grade_audit/outputs/nws.py.md
- [[nws.py Grade Audit]] - document - docs/grade_audit/outputs/nws.py.md
- [[nws_prob()]] - code - nws.py
- [[nws_prob() Zero Test Coverage, Unguarded Exception (710)]] - document - docs/grade_audit/outputs/nws.py.md
- [[nws_prob_from_quantiles() Upper-Tail Can Exceed 1.0 (710)]] - document - docs/grade_audit/outputs/nws.py.md
- [[paths.py]] - code - paths.py
- [[paths.py File Grade 810, pure constants module]] - document - docs/grade_audit/outputs/paths.py.md
- [[paths.py Grade Audit]] - document - docs/grade_audit/outputs/paths.py.md
- [[schema_validator.py]] - code - schema_validator.py
- [[schema_validator.py — Lightweight schema validation for external API responses.…]] - rationale - schema_validator.py
- [[utils.py]] - code - utils.py
- [[validate_forecast()]] - code - schema_validator.py
- [[validate_nws_response()]] - code - schema_validator.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/NWS/Circuit-Breaker_Data_Validation
SORT file.name ASC
```

## Connections to other communities
- 19 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 16 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 8 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 7 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 5 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 5 edges to [[_COMMUNITY_Community 59]]
- 4 edges to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 4 edges to [[_COMMUNITY_Community 82]]
- 4 edges to [[_COMMUNITY_Community 62]]
- 4 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 4 edges to [[_COMMUNITY_Community 32]]
- 3 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 3 edges to [[_COMMUNITY_Community 252]]
- 3 edges to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 3 edges to [[_COMMUNITY_Community 129]]
- 3 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 2 edges to [[_COMMUNITY_Forecast Persistent Cache]]
- 2 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_Community 84]]
- 2 edges to [[_COMMUNITY_Community 99]]
- 2 edges to [[_COMMUNITY_Community 164]]
- 2 edges to [[_COMMUNITY_Community 351]]
- 2 edges to [[_COMMUNITY_Community 198]]
- 2 edges to [[_COMMUNITY_Community 26]]
- 2 edges to [[_COMMUNITY_Community 181]]
- 2 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 95]]
- 1 edge to [[_COMMUNITY_Community 233]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Community 131]]
- 1 edge to [[_COMMUNITY_Community 356]]
- 1 edge to [[_COMMUNITY_Community 422]]
- 1 edge to [[_COMMUNITY_Community 454]]
- 1 edge to [[_COMMUNITY_Community 458]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 86]]
- 1 edge to [[_COMMUNITY_Community 119]]
- 1 edge to [[_COMMUNITY_Community 118]]
- 1 edge to [[_COMMUNITY_Community 293]]
- 1 edge to [[_COMMUNITY_Community 182]]
- 1 edge to [[_COMMUNITY_Community 195]]
- 1 edge to [[_COMMUNITY_Community 33]]
- 1 edge to [[_COMMUNITY_Community 94]]
- 1 edge to [[_COMMUNITY_Community 326]]
- 1 edge to [[_COMMUNITY_Community 55]]
- 1 edge to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 331]]
- 1 edge to [[_COMMUNITY_Community 503]]
- 1 edge to [[_COMMUNITY_Community 212]]
- 1 edge to [[_COMMUNITY_Community 194]]
- 1 edge to [[_COMMUNITY_Community 58]]
- 1 edge to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 1 edge to [[_COMMUNITY_Community 229]]
- 1 edge to [[_COMMUNITY_Community 567]]

## Top bridge nodes
- [[paths.py]] - degree 41, connects to 25 communities
- [[utils.py]] - degree 39, connects to 20 communities
- [[circuit_breaker.py]] - degree 20, connects to 13 communities
- [[nws.py]] - degree 37, connects to 11 communities
- [[schema_validator.py]] - degree 12, connects to 7 communities