---
type: community
cohesion: 0.06
members: 45
---

# Community 38

**Cohesion:** 0.06 - loosely connected
**Members:** 45 nodes

## Members
- [[26 Persistence baseline — models tomorrow's temperature as N(current_value,…]] - rationale - climatology.py
- [[dot-test_above_condition()_1]] - code - tests/test_forecasting.py
- [[dot-test_above_threshold_high_current()]] - code - tests/test_phase4.py
- [[dot-test_above_threshold_low_current()]] - code - tests/test_phase4.py
- [[dot-test_analyze_trade_blends_persistence_for_short_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_below_condition()_1]] - code - tests/test_forecasting.py
- [[dot-test_below_threshold_low_current()]] - code - tests/test_phase4.py
- [[dot-test_between_condition()_1]] - code - tests/test_forecasting.py
- [[dot-test_between_returns_reasonable_value()]] - code - tests/test_phase4.py
- [[dot-test_days_out_uses_city_local_today_not_utc()_1]] - code - tests/test_nws.py
- [[dot-test_get_model_brier_scores_empty_when_no_data()]] - code - tests/test_forecasting.py
- [[dot-test_get_model_brier_scores_excludes_models_with_few_rows()]] - code - tests/test_forecasting.py
- [[dot-test_get_model_brier_scores_returns_dict()]] - code - tests/test_forecasting.py
- [[dot-test_invalid_std_dev_returns_none()]] - code - tests/test_phase4.py
- [[dot-test_mean_returns_half()]] - code - tests/test_weather_markets.py
- [[dot-test_one_sigma_above_mean()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_for_zero_std()]] - code - tests/test_forecasting.py
- [[dot-test_shifted_mean()]] - code - tests/test_weather_markets.py
- [[dot-test_symmetry()]] - code - tests/test_weather_markets.py
- [[dot-test_two_sigma_above_mean()]] - code - tests/test_weather_markets.py
- [[dot-test_unknown_condition_returns_none()]] - code - tests/test_phase4.py
- [[dot-test_zero_sigma_returns_step()]] - code - tests/test_weather_markets.py
- [[Between condition with current value in range → decent probability.]] - rationale - tests/test_phase4.py
- [[CDF at +1 sigma ≈ 0.8413.]] - rationale - tests/test_weather_markets.py
- [[CDF at +2 sigma ≈ 0.9772.]] - rationale - tests/test_weather_markets.py
- [[CDF at mu with non-zero mu returns 0.5.]] - rationale - tests/test_weather_markets.py
- [[CDF at the mean of a standard normal is 0.5.]] - rationale - tests/test_weather_markets.py
- [[CDF(-x, 0, 1) == 1 - CDF(x, 0, 1) for all x.]] - rationale - tests/test_weather_markets.py
- [[Current value well above threshold → probability  0.5.]] - rationale - tests/test_phase4.py
- [[Current value well below threshold → probability  0.5.]] - rationale - tests/test_phase4.py
- [[Current value well below threshold → probability  0.5._1]] - rationale - tests/test_phase4.py
- [[Degenerate sigma=0 returns 1.0 when x = mu, 0.0 otherwise.]] - rationale - tests/test_weather_markets.py
- [[P(N(70, 5)  72) â‰ˆ 0.345.]] - rationale - tests/test_forecasting.py
- [[Probability that a Normal(mu, sigma) random variable is ≤ x. 30 Uses…]] - rationale - utils.py
- [[TestModelBrierScores]] - code - tests/test_forecasting.py
- [[TestNormalCdf]] - code - tests/test_weather_markets.py
- [[TestNwsProbDaysOutTimezone]] - code - tests/test_nws.py
- [[TestPersistenceProb]] - code - tests/test_forecasting.py
- [[TestPersistenceProb_1]] - code - tests/test_phase4.py
- [[analyze_trade includes persistence at 15% weight when days_out = 2.]] - rationale - tests/test_forecasting.py
- [[normal_cdf()]] - code - utils.py
- [[nws_prob's days_out (and thus sigma) must be computed against the city's own…]] - rationale - tests/test_nws.py
- [[persistence_prob()]] - code - climatology.py
- [[test_data_freshness.py (referenced, not in this chunk)]] - code - tests/test_data_freshness.py
- [[test_forecasting.py]] - code - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_38
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 5]]
- 6 edges to [[_COMMUNITY_Community 11]]
- 6 edges to [[_COMMUNITY_Community 4]]
- 4 edges to [[_COMMUNITY_Community 26]]
- 4 edges to [[_COMMUNITY_Community 68]]
- 3 edges to [[_COMMUNITY_Community 9]]
- 3 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 378]]
- 2 edges to [[_COMMUNITY_Community 460]]
- 2 edges to [[_COMMUNITY_Community 65]]
- 2 edges to [[_COMMUNITY_Community 102]]
- 1 edge to [[_COMMUNITY_Community 177]]
- 1 edge to [[_COMMUNITY_Community 178]]
- 1 edge to [[_COMMUNITY_Community 276]]
- 1 edge to [[_COMMUNITY_Community 277]]
- 1 edge to [[_COMMUNITY_Community 306]]
- 1 edge to [[_COMMUNITY_Community 417]]
- 1 edge to [[_COMMUNITY_Community 418]]
- 1 edge to [[_COMMUNITY_Community 461]]
- 1 edge to [[_COMMUNITY_Community 503]]
- 1 edge to [[_COMMUNITY_Community 565]]
- 1 edge to [[_COMMUNITY_Community 614]]
- 1 edge to [[_COMMUNITY_Community 203]]
- 1 edge to [[_COMMUNITY_Community 212]]
- 1 edge to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 356]]
- 1 edge to [[_COMMUNITY_Community 361]]
- 1 edge to [[_COMMUNITY_Community 396]]
- 1 edge to [[_COMMUNITY_Community 69]]
- 1 edge to [[_COMMUNITY_Community 89]]
- 1 edge to [[_COMMUNITY_Community 173]]
- 1 edge to [[_COMMUNITY_Community 33]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 14]]

## Top bridge nodes
- [[test_forecasting.py]] - degree 49, connects to 29 communities
- [[normal_cdf()]] - degree 24, connects to 8 communities
- [[persistence_prob()]] - degree 17, connects to 3 communities
- [[TestPersistenceProb]] - degree 7, connects to 1 community
- [[TestPersistenceProb_1]] - degree 7, connects to 1 community