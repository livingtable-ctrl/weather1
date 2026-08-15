---
type: community
cohesion: 0.05
members: 62
---

# Weather Probability Math Tests

**Cohesion:** 0.05 - loosely connected
**Members:** 62 nodes

## Members
- [[LOWER contains LOW -- confirms the substring check (not an exact-…]] - rationale - tests/test_weather.py
- [[LOWER contains LOW -- same substring-check behavior as…]] - rationale - tests/test_weather.py
- [[dot-_cond()]] - code - tests/test_weather.py
- [[dot-test_above_condition()]] - code - tests/test_weather.py
- [[dot-test_above_near_threshold_not_near_zero()]] - code - tests/test_weather.py
- [[dot-test_above_uses_prob_threshold()]] - code - tests/test_weather.py
- [[dot-test_above_uses_prob_threshold_not_raw_threshold()]] - code - tests/test_weather.py
- [[dot-test_below_condition()]] - code - tests/test_weather.py
- [[dot-test_below_near_threshold_not_near_one()]] - code - tests/test_weather.py
- [[dot-test_below_uses_prob_threshold()]] - code - tests/test_weather.py
- [[dot-test_below_uses_prob_threshold_not_raw_threshold()]] - code - tests/test_weather.py
- [[dot-test_between_condition()]] - code - tests/test_weather.py
- [[dot-test_centered_temp_gives_low_probability()]] - code - tests/test_weather.py
- [[dot-test_centered_temp_not_near_one()]] - code - tests/test_weather.py
- [[dot-test_falls_back_to_default_for_between_and_precip()]] - code - tests/test_weather.py
- [[dot-test_high_checked_before_low()]] - code - tests/test_weather.py
- [[dot-test_high_series_returns_max()]] - code - tests/test_weather.py
- [[dot-test_high_ticker_returns_max()]] - code - tests/test_weather.py
- [[dot-test_low_must_be_exact_substring_match()]] - code - tests/test_weather.py
- [[dot-test_low_must_be_exact_substring_match()_1]] - code - tests/test_weather.py
- [[dot-test_low_series_returns_min()]] - code - tests/test_weather.py
- [[dot-test_low_ticker_returns_min()]] - code - tests/test_weather.py
- [[dot-test_neither_high_nor_low_returns_none()]] - code - tests/test_weather.py
- [[dot-test_no_low_substring_defaults_to_max()]] - code - tests/test_weather.py
- [[dot-test_prefers_prob_threshold_when_present()]] - code - tests/test_weather.py
- [[dot-test_temp_outside_bucket_gives_low_probability()]] - code - tests/test_weather.py
- [[A very wide range around the forecast should have high probability.]] - rationale - tests/test_weather.py
- [[Codebase-wide single source of truth for the does this ticker's market measure…]] - rationale - weather_markets.py
- [[Compute P(outcome  condition) from raw ensemble members via empirical CDF.…]] - rationale - weather_markets.py
- [[Continuous-space decision boundary for probability math (Gaussian CDF, ensemble…]] - rationale - utils.py
- [[Convert a live observation to a probability. Uses sigma=3.5 — a midday…]] - rationale - nws.py
- [[Estimate probability of the market condition given a forecast temperature.]] - rationale - weather_markets.py
- [[If forecast equals threshold exactly, P(above) ~ 0.5.]] - rationale - tests/test_weather.py
- [[If forecast is much higher than threshold, P(below) ~ 0.]] - rationale - tests/test_weather.py
- [[Matches the original literal's exact fallback behavior — anything without LOW…]] - rationale - tests/test_weather.py
- [[Old sigma=0.25 gave ~0.95; new sigma=3.5 must give much less.]] - rationale - tests/test_weather.py
- [[Real, reachable case (not theoretical) -- e.g. an hourly KXTEMPxxxH ticker or a…]] - rationale - tests/test_weather.py
- [[Regression obs_prob for 'above''below' must use sigma=3.5, not sigma=1.0.…]] - rationale - tests/test_weather.py
- [[Regression obs_prob for 'between' must use sigma=3.5, not sigma=0.25. The old…]] - rationale - tests/test_weather.py
- [[Single source of truth for analyze_trade()'s own two var-derivation call sites…]] - rationale - weather_markets.py
- [[Temp 2°F above 'below' threshold → must be meaningfully below 1.]] - rationale - tests/test_weather.py
- [[Temp 2°F below 'above' threshold → must be meaningfully above 0.]] - rationale - tests/test_weather.py
- [[Temp 5°F above the bucket → probability should be tiny.]] - rationale - tests/test_weather.py
- [[Temp at centre of a 1°F band → ~11%, not ~95%.]] - rationale - tests/test_weather.py
- [[TestDailyVarFromSeries]] - code - tests/test_weather.py
- [[TestEnsembleCdfProbThresholdShift]] - code - tests/test_weather.py
- [[TestForecastProbability]] - code - tests/test_weather.py
- [[TestObsProbAboveBelowSigma]] - code - tests/test_weather.py
- [[TestObsProbBetweenSigma]] - code - tests/test_weather.py
- [[TestProbThresholdHelper]] - code - tests/test_weather.py
- [[TestVarFromTickerPrefix]] - code - tests/test_weather.py
- [[This codebase's real ticker vocabulary never contains both substrings…]] - rationale - tests/test_weather.py
- [[Unit tests for weather_markets.py — probability math, condition parsing, fee-…]] - rationale - tests/test_weather.py
- [[_daily_var_from_series()]] - code - weather_markets.py
- [[_forecast_probability()]] - code - weather_markets.py
- [[_var_from_ticker_prefix()]] - code - weather_markets.py
- [[backlog.txt NO MARKET-TYPE SEAM -- single source of truth for the…]] - rationale - tests/test_weather.py
- [[backlog.txt VAR-CONVENTION LITERAL HAND-COPIED ACROSS 7+ FILES BEYOND…]] - rationale - tests/test_weather.py
- [[ensemble_cdf_prob()]] - code - weather_markets.py
- [[obs_prob()]] - code - nws.py
- [[prob_threshold()]] - code - utils.py
- [[test_weather.py]] - code - tests/test_weather.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Weather_Probability_Math_Tests
SORT file.name ASC
```

## Connections to other communities
- 20 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 6 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 5 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 3 edges to [[_COMMUNITY_Community 82]]
- 3 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 2 edges to [[_COMMUNITY_Community 160]]
- 2 edges to [[_COMMUNITY_Kelly Sizing Property-Based Tests]]
- 2 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 2 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 323]]
- 1 edge to [[_COMMUNITY_Community 350]]
- 1 edge to [[_COMMUNITY_Community 415]]
- 1 edge to [[_COMMUNITY_Community 492]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Community 269]]
- 1 edge to [[_COMMUNITY_Community 331]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 570]]

## Top bridge nodes
- [[test_weather.py]] - degree 32, connects to 11 communities
- [[_var_from_ticker_prefix()]] - degree 19, connects to 7 communities
- [[prob_threshold()]] - degree 19, connects to 5 communities
- [[_forecast_probability()]] - degree 13, connects to 3 communities
- [[obs_prob()]] - degree 12, connects to 3 communities