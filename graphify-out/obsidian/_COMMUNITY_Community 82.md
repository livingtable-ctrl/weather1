---
type: community
cohesion: 0.08
members: 30
---

# Community 82

**Cohesion:** 0.08 - loosely connected
**Members:** 30 nodes

## Members
- [[dot-test_05_utc_ttl_is_approx_3600()]] - code - tests/test_phase4.py
- [[dot-test_after_all_cycles_wraps_to_next_day()]] - code - tests/test_phase4.py
- [[dot-test_days_out_uses_city_local_today_not_utc()_1]] - code - tests/test_nws.py
- [[dot-test_mean_returns_half()]] - code - tests/test_weather_markets.py
- [[dot-test_minimum_ttl_is_1800()]] - code - tests/test_phase4.py
- [[dot-test_one_sigma_above_mean()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_int()]] - code - tests/test_phase4.py
- [[dot-test_shifted_mean()]] - code - tests/test_weather_markets.py
- [[dot-test_symmetry()]] - code - tests/test_weather_markets.py
- [[dot-test_two_sigma_above_mean()]] - code - tests/test_weather_markets.py
- [[dot-test_zero_sigma_returns_step()]] - code - tests/test_weather_markets.py
- [[After 20 UTC, wraps to 02 UTC next day.]] - rationale - tests/test_phase4.py
- [[At 0500 UTC → TTL is roughly 3600s (until 0800 UTC availability).]] - rationale - tests/test_phase4.py
- [[CDF at +1 sigma ≈ 0.8413.]] - rationale - tests/test_weather_markets.py
- [[CDF at +2 sigma ≈ 0.9772.]] - rationale - tests/test_weather_markets.py
- [[CDF at mu with non-zero mu returns 0.5.]] - rationale - tests/test_weather_markets.py
- [[CDF at the mean of a standard normal is 0.5.]] - rationale - tests/test_weather_markets.py
- [[CDF(-x, 0, 1) == 1 - CDF(x, 0, 1) for all x.]] - rationale - tests/test_weather_markets.py
- [[Degenerate sigma=0 returns 1.0 when x = mu, 0.0 otherwise.]] - rationale - tests/test_weather_markets.py
- [[Minimum TTL is always at least 1800 seconds.]] - rationale - tests/test_phase4.py
- [[Probability that a Normal(mu, sigma) random variable is ≤ x. 30 Uses…]] - rationale - utils.py
- [[TTL is returned as int.]] - rationale - tests/test_phase4.py
- [[TestNormalCdf_1]] - code - tests/test_weather_markets.py
- [[TestNwsProbDaysOutTimezone]] - code - tests/test_nws.py
- [[TestTtlUntilNextCycle]] - code - tests/test_phase4.py
- [[Tests for nws.py's nws_prob() days_outsigma ladder.]] - rationale - tests/test_nws.py
- [[normal_cdf()]] - code - utils.py
- [[nws.nws_prob]] - code - nws.py
- [[nws_prob's days_out (and thus sigma) must be computed against the city's own…]] - rationale - tests/test_nws.py
- [[test_nws.py]] - code - tests/test_nws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_82
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 5 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 4 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 3 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 2 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 26]]

## Top bridge nodes
- [[normal_cdf()]] - degree 24, connects to 7 communities
- [[TestNormalCdf_1]] - degree 7, connects to 1 community
- [[test_nws.py]] - degree 5, connects to 1 community
- [[TestTtlUntilNextCycle]] - degree 5, connects to 1 community
- [[dot-test_05_utc_ttl_is_approx_3600()]] - degree 3, connects to 1 community